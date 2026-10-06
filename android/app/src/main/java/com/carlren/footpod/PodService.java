package com.carlren.footpod;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.*;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** One serial worker owns BLE operations, sensor state and recording files. */
@SuppressLint("MissingPermission")
public final class PodService extends Service {
    public interface Listener { void changed(Snapshot snapshot); }
    public static final class Snapshot {
        public String phase="disconnected",message="Connect to preview your foot pod",firmware="",address="",lastSession="";
        public boolean recording,charging,usb;
        public int batteryMv=-1,batteryPercent=-1,podCadence=-1,fitCadence;
        public long samples,missing,recordedSamples,cycles,imuErrors;
        public double hz,remaining,elapsed;
        public List<Protocol.Sample> graph=Collections.emptyList();
    }
    public final class LocalBinder extends Binder {
        public PodService service() { return PodService.this; }
    }
    private final IBinder binder=new LocalBinder();
    private volatile Snapshot snapshot=new Snapshot();
    private Listener listener;
    private HandlerThread thread;
    private Handler worker;
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private BluetoothGatt gatt;
    private String phase="disconnected",message="Connect to preview your foot pod",firmware="",address="",lastSession="";
    private boolean scanning,foreground;
    private int batteryMv=-1,batteryPct=-1,podCadence=-1;
    private boolean charging,usb;
    private long samples,lastSampleNs,imuErrors,notifyAt,recordedSamples;
    private double recordedDuration;
    private Protocol.Decoder decoder=new Protocol.Decoder();
    private Protocol.Detector detector=new Protocol.Detector();
    private final ArrayDeque<Protocol.Sample> graph=new ArrayDeque<>();
    private Session recording;
    private PowerManager.WakeLock wakeLock;
    private final ArrayDeque<Operation> queue=new ArrayDeque<>();
    private Operation pending;
    private final Runnable operationTimeout=()->fail("Bluetooth request timed out; reconnect the pod");
    private final Runnable connectTimeout=()-> { if(!phase.equals("preview")) fail("Could not connect. Check pod power and its two Bluetooth slots."); };

    private interface Start { boolean run(); }
    private static final class Operation {
        final String key; final Start start; final Runnable done;
        Operation(String key,Start start,Runnable done) { this.key=key; this.start=start; this.done=done; }
    }
    @Override public void onCreate() {
        super.onCreate();
        thread=new HandlerThread("FootPod-BLE-recording"); thread.start(); worker=new Handler(thread.getLooper());
        adapter=getSystemService(BluetoothManager.class).getAdapter();
        wakeLock=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"FootPodLab:recording");
        wakeLock.setReferenceCounted(false);
        NotificationChannel channel=new NotificationChannel("pod", "Foot pod connection",NotificationManager.IMPORTANCE_LOW);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
        worker.post(()-> { Session.recover(this); worker.post(tick); });
    }
    @Override public IBinder onBind(Intent intent) { return binder; }
    public Snapshot snapshot() { return snapshot; }
    public void listen(Listener value) { worker.post(()-> { listener=value; publish(); }); }
    @Override public int onStartCommand(Intent intent,int flags,int startId) {
        if(intent!=null && "DISCONNECT".equals(intent.getAction())) worker.post(()->disconnect("Disconnected",null));
        else {
            startForeground(1,notification("Connecting to foot pod")); foreground=true;
            worker.post(this::connect);
        }
        return START_NOT_STICKY;
    }
    private Notification notification(String text) {
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent disconnect=PendingIntent.getService(this,1,new Intent(this,PodService.class).setAction("DISCONNECT"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this,"pod").setSmallIcon(com.carlren.footpod.R.drawable.ic_pod)
            .setContentTitle("Foot Pod Lab").setContentText(text).setContentIntent(open).setOngoing(true)
            .addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource(this,com.carlren.footpod.R.drawable.ic_pod),"Disconnect",disconnect).build()).build();
    }
    private void connect() {
        if(!phase.equals("disconnected")) { publish(); return; }
        if(adapter==null || !adapter.isEnabled()) { fail("Turn on Bluetooth, then connect again"); return; }
        if(checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)!=PackageManager.PERMISSION_GRANTED ||
           checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED) { fail("Allow Nearby devices permission to connect"); return; }
        phase="scanning"; message="Looking for Carl Foot Pod…"; firmware=""; address="";
        samples=lastSampleNs=imuErrors=0; recordedSamples=0; recordedDuration=0;
        graph.clear(); decoder=new Protocol.Decoder(); detector=new Protocol.Detector(); podCadence=-1; batteryMv=batteryPct=-1;
        try {
            scanner=adapter.getBluetoothLeScanner();
            if(scanner==null) { fail("Bluetooth scanner unavailable"); return; }
            scanning=true;
            ScanFilter filter=new ScanFilter.Builder().setDeviceName("Carl Foot Pod").setServiceUuid(new ParcelUuid(Protocol.standard("1814"))).build();
            scanner.startScan(Collections.singletonList(filter),new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),scanCallback);
            worker.postDelayed(connectTimeout,25000); publish();
        } catch(Exception e) { fail("Bluetooth scan failed: "+e.getMessage()); }
    }
    private final ScanCallback scanCallback=new ScanCallback() {
        @Override public void onScanResult(int type,ScanResult result) {
            worker.post(()-> {
                if(!scanning) return;
                try {
                    stopScan(); address=result.getDevice().getAddress(); phase="connecting"; message="Connecting to Carl Foot Pod…";
                    gatt=result.getDevice().connectGatt(PodService.this,false,callback,BluetoothDevice.TRANSPORT_LE,BluetoothDevice.PHY_LE_1M_MASK,worker);
                    if(gatt==null) fail("Bluetooth connection could not start"); else publish();
                } catch(Exception e) { fail("Connection failed: "+e.getMessage()); }
            });
        }
        @Override public void onScanFailed(int code) { worker.post(()->fail("Bluetooth scan failed ("+code+"). Wait a few seconds and retry.")); }
    };
    private void stopScan() {
        if(scanning) { scanning=false; try { if(scanner!=null) scanner.stopScan(scanCallback); } catch(SecurityException ignored) {} }
    }
    private BluetoothGattCharacteristic characteristic(UUID uuid) {
        if(gatt!=null) for(BluetoothGattService service:gatt.getServices()) {
            BluetoothGattCharacteristic c=service.getCharacteristic(uuid); if(c!=null) return c;
        }
        throw new IllegalStateException("Pod is missing "+uuid+". Install firmware 0.4.0 or later.");
    }
    private void enqueue(Operation op) { if(gatt!=null) { queue.add(op); pump(); } }
    private void pump() {
        if(pending!=null || queue.isEmpty() || gatt==null) return;
        pending=queue.remove();
        try {
            if(!pending.start.run()) { fail("Bluetooth request could not start; reconnect the pod"); return; }
            worker.postDelayed(operationTimeout,12000);
        } catch(Exception e) { fail(e.getMessage()); }
    }
    private void completed(String key,int status) {
        if(pending==null || !pending.key.equals(key)) { fail("Unexpected Bluetooth response; reconnect the pod"); return; }
        worker.removeCallbacks(operationTimeout);
        if(status!=BluetoothGatt.GATT_SUCCESS) { fail("Bluetooth request failed ("+status+")"); return; }
        Operation finished=pending; pending=null;
        if(finished.done!=null) finished.done.run();
        pump();
    }
    private void read(UUID uuid) { enqueue(new Operation("R"+uuid,()->gatt.readCharacteristic(characteristic(uuid)),null)); }
    @SuppressWarnings("deprecation")
    private void subscribe(UUID uuid) {
        enqueue(new Operation("D"+uuid,()-> {
            BluetoothGattCharacteristic c=characteristic(uuid);
            BluetoothGattDescriptor d=c.getDescriptor(Protocol.CCCD);
            if(d==null || !gatt.setCharacteristicNotification(c,true)) return false;
            if(Build.VERSION.SDK_INT>=33) return gatt.writeDescriptor(d,BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)==BluetoothStatusCodes.SUCCESS;
            d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE); return gatt.writeDescriptor(d);
        },null));
    }
    @SuppressWarnings("deprecation")
    private void startCapture() {
        enqueue(new Operation("W"+Protocol.CONTROL,()-> {
            BluetoothGattCharacteristic c=characteristic(Protocol.CONTROL); byte[] value={1};
            if(Build.VERSION.SDK_INT>=33) return gatt.writeCharacteristic(c,value,BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)==BluetoothStatusCodes.SUCCESS;
            c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT); c.setValue(value); return gatt.writeCharacteristic(c);
        },()-> { phase="preview"; message="Live preview · ready to record"; lastSampleNs=SystemClock.elapsedRealtimeNanos(); worker.removeCallbacks(connectTimeout); publish(); }));
    }
    private final BluetoothGattCallback callback=new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g,int status,int state) {
            if(g!=gatt) return;
            if(status!=BluetoothGatt.GATT_SUCCESS || state==BluetoothProfile.STATE_DISCONNECTED) { fail("Bluetooth disconnected ("+status+"); any partial recording was saved"); return; }
            if(state==BluetoothProfile.STATE_CONNECTED) {
                phase="connecting"; message="Reading pod services…";
                // Do not negotiate MTU: the protocol intentionally fits the 20-byte minimum.
                g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH);
                if(!g.discoverServices()) fail("Could not discover pod services"); else publish();
            }
        }
        @Override public void onServicesDiscovered(BluetoothGatt g,int status) {
            if(g!=gatt) return;
            if(status!=BluetoothGatt.GATT_SUCCESS) { fail("Service discovery failed"); return; }
            try {
                for(UUID u:Arrays.asList(Protocol.DATA,Protocol.CONTROL,Protocol.STATUS,Protocol.VOLTAGE,Protocol.LEVEL,Protocol.CADENCE,Protocol.FIRMWARE)) characteristic(u);
                // Firmware, IMU readiness, battery, subscriptions, then capture.
                queue.add(new Operation("R"+Protocol.FIRMWARE,()->gatt.readCharacteristic(characteristic(Protocol.FIRMWARE)),null));
                read(Protocol.STATUS); read(Protocol.VOLTAGE); read(Protocol.LEVEL);
                subscribe(Protocol.CADENCE); subscribe(Protocol.LEVEL); subscribe(Protocol.DATA); startCapture();
            } catch(Exception e) { fail(e.getMessage()); }
        }
        @Override public void onDescriptorWrite(BluetoothGatt g,BluetoothGattDescriptor d,int status) {
            if(g==gatt) completed("D"+d.getCharacteristic().getUuid(),status);
        }
        @Override public void onCharacteristicWrite(BluetoothGatt g,BluetoothGattCharacteristic c,int status) {
            if(g==gatt) completed("W"+c.getUuid(),status);
        }
        @Override public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value,int status) {
            if(g!=gatt) return;
            if(status==BluetoothGatt.GATT_SUCCESS && !value(c.getUuid(),value)) return;
            completed("R"+c.getUuid(),status);
        }
        @Override @SuppressWarnings("deprecation") public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,int status) {
            if(Build.VERSION.SDK_INT<33) onCharacteristicRead(g,c,c.getValue().clone(),status);
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value) {
            if(g==gatt) value(c.getUuid(),value);
        }
        @Override @SuppressWarnings("deprecation") public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c) {
            if(Build.VERSION.SDK_INT<33) onCharacteristicChanged(g,c,c.getValue().clone());
        }
    };
    private boolean value(UUID uuid,byte[] bytes) {
        try {
            if(uuid.equals(Protocol.DATA)) {
                long now=SystemClock.elapsedRealtimeNanos();
                Protocol.Sample s=decoder.decode(bytes,now); s.stride=detector.update(s.gyro[1],s.deviceUs);
                s.filtered=detector.filtered; s.fitted=detector.cadence(s.deviceUs);
                samples++; lastSampleNs=now; graph.add(s); while(graph.size()>2160) graph.remove();
                if(recording!=null) {
                    if(recording.window.accepts(s)) recording.append(s);
                    else finishRecording(null,false);
                }
            } else if(uuid.equals(Protocol.CADENCE)) podCadence=Protocol.cadence(bytes);
            else if(uuid.equals(Protocol.LEVEL)) batteryPct=Protocol.percent(bytes);
            else if(uuid.equals(Protocol.VOLTAGE)) {
                int[] values=Protocol.voltage(bytes); batteryMv=values[0]; charging=values[2]!=0; usb=values[3]!=0;
            } else if(uuid.equals(Protocol.STATUS)) {
                long[] values=Protocol.status(bytes); imuErrors=values[4];
                if((values[0]&1)==0 || values[1]!=0x6a) throw new IllegalStateException("Pod IMU is not ready");
            } else if(uuid.equals(Protocol.FIRMWARE)) firmware=new String(bytes,StandardCharsets.UTF_8);
            return true;
        } catch(Exception e) { fail("Pod / recording error: "+e.getMessage()); return false; }
    }
    public void record(String label,double seconds,Double reference,Double speed) {
        worker.post(()-> {
            if(!phase.equals("preview") || recording!=null || samples==0) { message="Wait for live samples before recording"; publish(); return; }
            try {
                if(reference!=null && (!Double.isFinite(reference) || reference<=0 || reference>500)) throw new IllegalArgumentException("Reference must be 1–500 steps/min");
                if(speed!=null && (!Double.isFinite(speed) || speed<=0 || speed>30)) throw new IllegalArgumentException("Speed must be 0–30 mph");
                recording=new Session(this,label,seconds,reference,speed,address,firmware,battery(),SystemClock.elapsedRealtimeNanos());
                wakeLock.acquire((long)(seconds*1000)+10000); recordedSamples=0; recordedDuration=0;
                message="Recording · count steps from both feet"; publish();
            } catch(Exception e) { message="Cannot record: "+e.getMessage(); if(recording!=null) finishRecording(message,false); publish(); }
        });
    }
    public void stopRecording() { worker.post(()-> { finishRecording(null,true); publish(); }); }
    public void disconnect() { worker.post(()->disconnect("Disconnected",null)); }
    private JSONObject battery() throws Exception {
        return new JSONObject().put("voltage_v",batteryMv/1000.0).put("percent",batteryPct).put("percent_estimated",true).put("charging",charging).put("usb_power",usb);
    }
    private void finishRecording(String error,boolean stopped) {
        if(recording==null) return;
        Session saved=recording; recording=null;
        recordedSamples=saved.window.samples; recordedDuration=saved.window.duration(); lastSession=saved.directory.getName();
        try { saved.finish(error,stopped); message=error==null ? "Saved recording · preview continues" : error; }
        catch(Exception e) { message="Recording files retained; final save failed: "+e.getMessage(); }
        if(wakeLock.isHeld()) wakeLock.release();
    }
    private void fail(String reason) { disconnect(reason,reason); }
    private void disconnect(String text,String error) {
        finishRecording(error,true); stopScan(); worker.removeCallbacks(connectTimeout); worker.removeCallbacks(operationTimeout);
        BluetoothGatt old=gatt; gatt=null; queue.clear(); pending=null;
        if(old!=null) { try { old.disconnect(); } catch(SecurityException ignored) {} old.close(); }
        phase="disconnected"; message=text;
        if(foreground) { foreground=false; stopForeground(STOP_FOREGROUND_REMOVE); stopSelf(); }
        publish();
    }
    private final Runnable tick=new Runnable() {
        long pollAt;
        @Override public void run() {
            long now=SystemClock.elapsedRealtimeNanos();
            if(recording!=null && now>=recording.window.deadlineNs) finishRecording(null,false);
            if(phase.equals("preview")) {
                if(now-lastSampleNs>3000000000L) fail("No IMU samples for 3 seconds; partial recording saved");
                else if(now-pollAt>5000000000L && pending==null && queue.isEmpty()) {
                    pollAt=now; read(Protocol.VOLTAGE); read(Protocol.LEVEL);
                }
            }
            publish();
            if(foreground && now-notifyAt>1000000000L) {
                notifyAt=now; getSystemService(NotificationManager.class).notify(1,notification(recording==null ? message :
                    "Recording · "+(int)Math.ceil(recording.window.remaining(now))+" seconds remaining"));
            }
            worker.postDelayed(this,200);
        }
    };
    private void publish() {
        Snapshot s=new Snapshot(); s.phase=phase; s.message=message; s.firmware=firmware; s.address=address; s.lastSession=lastSession;
        s.recording=recording!=null; s.batteryMv=batteryMv; s.batteryPercent=batteryPct; s.charging=charging; s.usb=usb;
        s.podCadence=podCadence; s.samples=samples; s.cycles=detector.cycles; s.imuErrors=imuErrors;
        if(!graph.isEmpty()) {
            Protocol.Sample last=graph.peekLast(),first=graph.peekFirst();
            s.missing=last.missing; s.fitCadence=(int)last.fitted;
            if(graph.size()>1 && last.elapsedUs>first.elapsedUs) s.hz=(graph.size()-1)*1000000.0/(last.elapsedUs-first.elapsedUs);
        }
        s.graph=new ArrayList<>(graph); s.recordedSamples=recording==null ? recordedSamples : recording.window.samples;
        s.elapsed=recording==null ? recordedDuration : (SystemClock.elapsedRealtimeNanos()-recording.window.startedNs)/1e9;
        s.remaining=recording==null ? 0 : recording.window.remaining(SystemClock.elapsedRealtimeNanos());
        snapshot=s; if(listener!=null) listener.changed(s);
    }
    @Override public void onDestroy() {
        worker.post(()-> { disconnect("Disconnected", "App service stopped; partial recording saved"); worker.removeCallbacksAndMessages(null); thread.quitSafely(); });
        super.onDestroy();
    }
}
