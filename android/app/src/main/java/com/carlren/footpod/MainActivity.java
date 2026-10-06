package com.carlren.footpod;

import android.Manifest;
import android.app.*;
import android.bluetooth.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.File;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

public final class MainActivity extends Activity {
    private static final int BG=0xff101820,CARD=0xff1b2732,TEXT=0xfff0f5f8,MUTED=0xffaebdc8,ACCENT=0xff81eebc;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private PodService pod;
    private boolean bound;
    private LinearLayout content;
    private TextView state,battery,spm,fit,timer,quality,recordHint,sessionInfo;
    private EditText label,seconds,reference,speed,steps;
    private Button connect,record,share,count,sessions;
    private ProgressBar progress;
    private Plot gyro,accel;
    private File selected;
    private String seenLast="";
    private PodService.Snapshot current=new PodService.Snapshot();
    private final ServiceConnection connection=new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name,IBinder binder) {
            pod=((PodService.LocalBinder)binder).service(); pod.listen(s->ui.post(()->render(s))); render(pod.snapshot());
        }
        @Override public void onServiceDisconnected(ComponentName name) { pod=null; render(new PodService.Snapshot()); }
    };
    private int dp(float n) { return Math.round(n*getResources().getDisplayMetrics().density); }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll=new ScrollView(this); scroll.setBackgroundColor(BG); scroll.setFillViewport(true);
        content=new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(20),dp(20),dp(20),dp(32));
        scroll.addView(content); setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v,insets)-> {
            android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout()|WindowInsets.Type.ime());
            v.setPadding(bars.left,bars.top,bars.right,bars.bottom); return insets;
        });
        content.addView(text("FOOT POD LAB",12,ACCENT,true));
        content.addView(text("Find your rhythm.",32,TEXT,true));
        content.addView(text("Live motion, cadence and recordings",14,MUTED,false));
        space(20);
        LinearLayout connectionCard=card();
        this.state=text("Disconnected",17,TEXT,true); connectionCard.addView(this.state);
        battery=text("Battery — · connect to read",14,MUTED,false); connectionCard.addView(battery);
        LinearLayout buttons=row(); connectionCard.addView(buttons);
        connect=button("Connect",ACCENT,buttons); connect.setOnClickListener(v->connectOrDisconnect());
        record=button("Record",0xff95bbff,buttons); record.setOnClickListener(v->recordOrStop());
        record.setEnabled(false);
        recordHint=text("Connect to see samples. Record saves only new samples.",13,MUTED,false); connectionCard.addView(recordHint);
        LinearLayout cadence=card(); cadence.addView(text("TOTAL CADENCE",11,MUTED,true));
        spm=text("— steps/min",40,TEXT,true); cadence.addView(spm);
        fit=text("Gyro fit — · one shoe, both feet",14,ACCENT,false); cadence.addView(fit);
        quality=text("Waiting for live samples",13,MUTED,false); cadence.addView(quality);
        LinearLayout timerCard=card(); timerCard.addView(text("RECORDING TIMER",11,MUTED,true));
        timer=text("01:00",44,TEXT,true); timer.setTypeface(Typeface.MONOSPACE); timerCard.addView(timer);
        progress=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal); progress.setMax(1000); timerCard.addView(progress,new LinearLayout.LayoutParams(-1,dp(8)));
        LinearLayout fields=row(); timerCard.addView(fields);
        seconds=field("Duration · seconds","60",InputType.TYPE_CLASS_NUMBER,fields);
        Button minute=button("Use 60 s",0xff324557,fields); minute.setTextColor(TEXT); minute.setOnClickListener(v->seconds.setText("60"));
        label=field("Activity label","walking",InputType.TYPE_CLASS_TEXT,timerCard);
        LinearLayout annotations=row(); timerCard.addView(annotations);
        reference=field("Reference · steps/min","",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL,annotations);
        speed=field("Speed · mph (optional)","",InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL,annotations);
        timerCard.addView(text("Count steps from both feet. Save the count after recording. The timer stops automatically and preview stays live.",13,MUTED,false));
        LinearLayout motion=card(); motion.addView(text("GYROSCOPE · °/s",12,TEXT,true));
        motion.addView(text("X cyan · Y amber · Z violet · fitted Y white",12,MUTED,false));
        gyro=new Plot(true); motion.addView(gyro,new LinearLayout.LayoutParams(-1,dp(210)));
        motion.addView(text("Green markers show detected stride cycles. One shoe cycle is two total steps; markers are not measured touchdown times.",12,MUTED,false));
        LinearLayout acceleration=card(); acceleration.addView(text("ACCELEROMETER · g",12,TEXT,true));
        acceleration.addView(text("X cyan · Y amber · Z violet · secondary signal",12,MUTED,false));
        accel=new Plot(false); acceleration.addView(accel,new LinearLayout.LayoutParams(-1,dp(190)));
        LinearLayout saved=card(); saved.addView(text("SAVED RECORDINGS",12,TEXT,true));
        sessionInfo=text("No recording selected",14,MUTED,false); saved.addView(sessionInfo);
        sessions=button("Choose recording",0xff324557,saved); sessions.setTextColor(TEXT); sessions.setOnClickListener(v->chooseSession());
        steps=field("Counted steps · both feet","",InputType.TYPE_CLASS_NUMBER,saved);
        count=button("Calculate & save reference",0xff324557,saved); count.setTextColor(TEXT); count.setOnClickListener(v->saveCount());
        share=button("Share recording ZIP",ACCENT,saved); share.setOnClickListener(v->shareSession());
        saved.addView(text("The ZIP contains raw IMU, gyro fit and session details. Choose Drive in the share menu to upload. Recordings stay on this phone until you share them.",13,MUTED,false));
        content.addView(text("Works alongside Zwift on another device. Battery % is a voltage-based estimate. Firmware 0.4.0 or newer is required.",12,MUTED,false));
        selectLatest(); render(current);
    }
    private TextView text(String value,int size,int color,boolean bold) {
        TextView t=new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0,dp(4),0,dp(6));
        if(bold) t.setTypeface(Typeface.DEFAULT,Typeface.BOLD); return t;
    }
    private LinearLayout card() {
        LinearLayout c=new LinearLayout(this); c.setOrientation(LinearLayout.VERTICAL); c.setPadding(dp(16),dp(12),dp(16),dp(16));
        GradientDrawable bg=new GradientDrawable(); bg.setColor(CARD); bg.setCornerRadius(dp(20)); c.setBackground(bg);
        LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2); p.bottomMargin=dp(14); content.addView(c,p); return c;
    }
    private LinearLayout row() { LinearLayout r=new LinearLayout(this); r.setOrientation(LinearLayout.HORIZONTAL); return r; }
    private void space(int n) { View v=new View(this); content.addView(v,new LinearLayout.LayoutParams(1,dp(n))); }
    private Button button(String title,int color,LinearLayout parent) {
        Button b=new Button(this); b.setText(title); b.setAllCaps(false); b.setTextSize(14); b.setTextColor(BG); b.setMinHeight(dp(52));
        GradientDrawable bg=new GradientDrawable(); bg.setColor(color); bg.setCornerRadius(dp(12)); b.setBackground(bg);
        LinearLayout.LayoutParams p=parent.getOrientation()==LinearLayout.HORIZONTAL ? new LinearLayout.LayoutParams(0,-2,1) : new LinearLayout.LayoutParams(-1,-2);
        p.topMargin=dp(10); if(parent.getOrientation()==LinearLayout.HORIZONTAL) p.setMargins(dp(3),dp(10),dp(3),0);
        parent.addView(b,p); return b;
    }
    private EditText field(String hint,String value,int type,LinearLayout parent) {
        LinearLayout group=new LinearLayout(this); group.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams p=parent.getOrientation()==LinearLayout.HORIZONTAL ? new LinearLayout.LayoutParams(0,-2,1) : new LinearLayout.LayoutParams(-1,-2);
        p.topMargin=dp(8); p.rightMargin=dp(6); parent.addView(group,p); group.addView(text(hint,12,MUTED,false));
        EditText edit=new EditText(this); edit.setInputType(type); edit.setTextColor(TEXT); edit.setTextSize(16); edit.setText(value); edit.setSingleLine(true); edit.setSelectAllOnFocus(true);
        group.addView(edit,new LinearLayout.LayoutParams(-1,dp(48))); return edit;
    }
    @Override public void onStart() {
        super.onStart(); bound=bindService(new Intent(this,PodService.class),connection,BIND_AUTO_CREATE);
    }
    @Override public void onStop() {
        if(pod!=null) pod.listen(null);
        if(bound) { unbindService(connection); bound=false; } pod=null; super.onStop();
    }
    private void connectOrDisconnect() {
        if(!current.phase.equals("disconnected")) { if(pod!=null) pod.disconnect(); return; }
        if(checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)!=PackageManager.PERMISSION_GRANTED || checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED) {
            List<String> permissions=new ArrayList<>(Arrays.asList(Manifest.permission.BLUETOOTH_SCAN,Manifest.permission.BLUETOOTH_CONNECT));
            if(Build.VERSION.SDK_INT>=33) permissions.add(Manifest.permission.POST_NOTIFICATIONS);
            requestPermissions(permissions.toArray(new String[0]),10); return;
        }
        BluetoothAdapter adapter=getSystemService(BluetoothManager.class).getAdapter();
        if(adapter==null) { toast("Bluetooth is unavailable"); return; }
        if(!adapter.isEnabled()) { startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),11); return; }
        try { startForegroundService(new Intent(this,PodService.class).setAction("CONNECT")); }
        catch(Exception e) { toast("Connection could not start: "+e.getMessage()); }
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(request,permissions,results);
        if(request==10) {
            if(checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)==PackageManager.PERMISSION_GRANTED && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)==PackageManager.PERMISSION_GRANTED) connectOrDisconnect();
            else toast("Allow Nearby devices in app settings to connect");
        }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data); if(request==11 && result==RESULT_OK) connectOrDisconnect();
    }
    private Double optional(EditText e) {
        String value=e.getText().toString().trim(); return value.isEmpty()?null:Double.valueOf(value);
    }
    private void recordOrStop() {
        if(pod==null) return;
        if(current.recording) { pod.stopRecording(); return; }
        try { pod.record(label.getText().toString().trim(),Double.parseDouble(seconds.getText().toString()),optional(reference),optional(speed)); }
        catch(Exception e) { toast("Check duration, reference and speed values"); }
    }
    private String clock(double seconds) { int n=(int)Math.ceil(Math.max(0,seconds)); return String.format(Locale.US,"%02d:%02d",n/60,n%60); }
    private void render(PodService.Snapshot s) {
        if(isDestroyed()) return; current=s;
        state.setText(s.message);
        battery.setText(s.batteryMv<0 ? "Battery — · connect to read" : String.format(Locale.US,"%.3f V · ~%d%% · %s",s.batteryMv/1000.0,s.batteryPercent,s.usb?(s.charging?"charging":"USB connected"):"battery power"));
        connect.setText(s.phase.equals("disconnected")?"Connect":"Disconnect");
        record.setText(s.recording?"Stop recording":"Record"); record.setEnabled(s.phase.equals("preview") && s.samples>0); record.setAlpha(record.isEnabled()?1:.4f);
        recordHint.setText(s.recording?"Saving new samples · continues with the screen locked":s.phase.equals("preview")?"Preview is live; files start only when you tap Record.":"Connect to see samples. Record saves only new samples.");
        spm.setText(s.podCadence<0 ? "— steps/min" : s.podCadence+" steps/min");
        fit.setText(s.samples==0?"Gyro fit — · waiting for samples":"Gyro fit "+s.fitCadence+" steps/min · "+s.cycles+" stride cycles");
        quality.setText(String.format(Locale.US,"%.1f Hz · %,d samples · %,d gaps%s",s.hz,s.samples,s.missing,s.firmware.isEmpty()?"":" · fw "+s.firmware));
        double duration=60; try { duration=Double.parseDouble(seconds.getText().toString()); } catch(Exception ignored) {}
        timer.setText(s.recording?clock(s.remaining):(s.recordedSamples>0?"Saved "+clock(s.elapsed):clock(duration)));
        progress.setProgress(s.recording && s.elapsed+s.remaining>0 ? (int)(1000*s.elapsed/(s.elapsed+s.remaining)) : s.recordedSamples>0?1000:0);
        for(EditText e:Arrays.asList(label,seconds,reference,speed)) e.setEnabled(!s.recording);
        share.setEnabled(selected!=null && !s.recording); count.setEnabled(selected!=null && !s.recording); sessions.setEnabled(!s.recording);
        gyro.setSamples(s.graph); accel.setSamples(s.graph);
        if(!s.lastSession.isEmpty() && !s.lastSession.equals(seenLast)) { seenLast=s.lastSession; selected=new File(Session.root(this),s.lastSession); updateSelected(); }
    }
    private List<File> saved() {
        File[] files=Session.root(this).listFiles(f->f.isDirectory() && new File(f,"session.json").isFile());
        List<File> list=files==null?new ArrayList<>():new ArrayList<>(Arrays.asList(files));
        list.sort(Comparator.comparing(File::getName).reversed()); return list;
    }
    private void selectLatest() { List<File> files=saved(); if(!files.isEmpty()) { selected=files.get(0); updateSelected(); } }
    private String description(File f) {
        try {
            JSONObject m=Session.read(f);
            String date=DateTimeFormatter.ofPattern("MMM d, HH:mm",Locale.US).withZone(ZoneId.systemDefault()).format(Instant.parse(m.getString("started_utc")));
            return m.optString("label","Recording")+" · "+date+" · "+String.format(Locale.US,"%.1f s",m.optDouble("device_duration_s",0))+(m.optBoolean("completed")?"":" · partial");
        } catch(Exception e) { return "Recording · details unavailable"; }
    }
    private void updateSelected() {
        if(selected==null) { sessionInfo.setText("No recording selected"); return; }
        try {
            JSONObject m=Session.read(selected);
            String ref=m.isNull("reference_spm")?"":String.format(Locale.US,"\nReference %.1f steps/min",m.optDouble("reference_spm"));
            sessionInfo.setText(description(selected)+"\n"+m.optLong("samples")+" samples · "+m.optLong("missing_packets")+" gaps"+ref+(m.has("error")?"\n"+m.optString("error"):""));
            steps.setText(m.has("reference_total_steps")?String.valueOf(m.getInt("reference_total_steps")):"");
        } catch(Exception e) { sessionInfo.setText("Raw files retained; session details unavailable"); }
    }
    private void chooseSession() {
        List<File> list=saved(); if(list.isEmpty()) { toast("Record a session first"); return; }
        String[] descriptions=list.stream().map(this::description).toArray(String[]::new);
        new AlertDialog.Builder(this).setTitle("Recordings").setItems(descriptions,(d,index)-> { selected=list.get(index); updateSelected(); render(current); }).show();
    }
    private void saveCount() {
        if(selected==null || current.recording) return;
        try {
            int n=Integer.parseInt(steps.getText().toString()); if(n<=0 || n>100000) throw new IllegalArgumentException();
            JSONObject m=Session.read(selected); double duration=m.getDouble("device_duration_s");
            if(duration<=0 || m.optBoolean("recording")) throw new IllegalArgumentException();
            m.put("reference_total_steps",n).put("reference_count_seconds",duration).put("reference_spm",n*60/duration)
                .put("reference_source","user_reported_count").put("reference_steps_scope","both_feet");
            Session.save(selected,m); updateSelected(); toast("Reference saved");
        } catch(Exception e) { toast("Enter a positive total count for a finished recording"); }
    }
    private void shareSession() {
        if(selected==null || current.recording) return;
        File chosen=selected; share.setEnabled(false);
        new Thread(()-> {
            try {
                File zip=Session.export(this,chosen);
                Uri uri=new Uri.Builder().scheme("content").authority("com.carlren.footpod.sessions").appendPath(zip.getName()).build();
                Intent send=new Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM,uri)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                send.setClipData(ClipData.newRawUri("Foot pod recording",uri));
                ui.post(()-> { if(!isDestroyed()) { share.setEnabled(true); startActivity(Intent.createChooser(send,"Share recording — choose Drive")); } });
            } catch(Exception e) { ui.post(()-> { if(!isDestroyed()) { share.setEnabled(true); toast("Export failed: "+e.getMessage()); } }); }
        },"FootPod-export").start();
    }
    private void toast(String text) { Toast.makeText(this,text,Toast.LENGTH_LONG).show(); }

    private final class Plot extends View {
        private final boolean rotation;
        private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path=new Path();
        private List<Protocol.Sample> data=Collections.emptyList();
        private final int[] colors={0xff6dd6ff,0xffffcd78,0xffbd9dff,0xfff0f5f8};
        Plot(boolean rotation) { super(MainActivity.this); this.rotation=rotation; setContentDescription(rotation?"Live gyroscope X, Y, Z and fitted Y rotation, with stride markers":"Live acceleration X, Y and Z"); }
        void setSamples(List<Protocol.Sample> values) { data=values; invalidate(); }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); float left=dp(40),right=getWidth()-dp(4),top=dp(12),bottom=getHeight()-dp(24);
            if(right<=left || bottom<=top) return;
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(1)); paint.setColor(0xff354451);
            for(int i=0;i<5;i++) { float y=top+(bottom-top)*i/4; canvas.drawLine(left,y,right,y,paint); }
            paint.setStyle(Paint.Style.FILL); paint.setTextSize(dp(10)); paint.setColor(MUTED);
            double limit=rotation?80:1.5;
            long last=data.isEmpty()?0:data.get(data.size()-1).elapsedUs, start=last-20000000;
            for(Protocol.Sample s:data) if(s.elapsedUs>=start) for(float n:rotation?s.gyro:s.accel) limit=Math.max(limit,Math.abs(n)*1.15);
            limit=Math.ceil(limit*(rotation?1:10))/(rotation?1:10);
            canvas.drawText(String.format(Locale.US,rotation?"%.0f":"%.1f",limit),0,top+dp(8),paint);
            canvas.drawText("0",dp(24),(top+bottom)/2+dp(3),paint);
            canvas.drawText(String.format(Locale.US,rotation?"%.0f":"%.1f",-limit),0,bottom,paint);
            canvas.drawText("−20 s",left,bottom+dp(18),paint); canvas.drawText("now",right-dp(24),bottom+dp(18),paint);
            canvas.save(); canvas.clipRect(left,top,right,bottom);
            if(rotation) {
                paint.setColor(0xff416452); paint.setStrokeWidth(dp(1));
                canvas.drawLine(left,(float)((top+bottom)/2-40*(bottom-top)/(2*limit)),right,(float)((top+bottom)/2-40*(bottom-top)/(2*limit)),paint);
                for(Protocol.Sample s:data) if(s.stride && s.elapsedUs>=start) {
                    float x=left+(right-left)*(s.elapsedUs-start)/20000000f; canvas.drawLine(x,top,x,bottom,paint);
                }
            }
            for(int axis=0;axis<(rotation?4:3);axis++) {
                path.reset(); boolean first=true;
                for(Protocol.Sample s:data) if(s.elapsedUs>=start) {
                    float value=axis==3?s.filtered:(rotation?s.gyro[axis]:s.accel[axis]);
                    float x=left+(right-left)*(s.elapsedUs-start)/20000000f, y=(float)((top+bottom)/2-value*(bottom-top)/(2*limit));
                    if(first) { path.moveTo(x,y); first=false; } else path.lineTo(x,y);
                }
                paint.setStyle(Paint.Style.STROKE); paint.setColor(colors[axis]); paint.setStrokeWidth(dp(axis==3?2:1)); canvas.drawPath(path,paint);
            }
            canvas.restore();
        }
    }
}
