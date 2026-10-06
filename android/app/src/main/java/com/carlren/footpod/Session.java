package com.carlren.footpod;

import android.content.Context;
import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Instant;
import java.util.Locale;
import java.util.UUID;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Files are created only by Record; preview does not open a session. */
final class Session {
    final File directory;
    final JSONObject metadata=new JSONObject();
    final Protocol.RecordingWindow window;
    private final BufferedWriter imu, fit;
    private long clipped, gaps, maxInterval, lastUs=-1;
    static File root(Context c) { return new File(c.getFilesDir(),"recordings"); }
    static JSONObject read(File directory) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(new File(directory,"session.json").toPath()),StandardCharsets.UTF_8));
    }
    static void save(File directory, JSONObject metadata) throws Exception {
        AtomicFile file=new AtomicFile(new File(directory,"session.json"));
        FileOutputStream stream=file.startWrite();
        try { stream.write((metadata.toString(2)+"\n").getBytes(StandardCharsets.UTF_8)); file.finishWrite(stream); }
        catch(Exception e) { file.failWrite(stream); throw e; }
    }
    Session(Context c, String label, double seconds, Double reference, Double speed,
            String address, String firmware, JSONObject battery, long nowNs) throws Exception {
        if(label.trim().isEmpty() || label.length()>64 || label.contains("\n")) throw new IllegalArgumentException("Enter an activity label (1–64 characters)");
        window=new Protocol.RecordingWindow(nowNs,seconds);
        directory=new File(root(c),Instant.now().toString().replace(":", "-")+"_"+UUID.randomUUID().toString().substring(0,8));
        if(!directory.mkdirs()) throw new IOException("Cannot create recording folder");
        BufferedWriter first=null,second=null;
        try {
            metadata.put("started_utc",Instant.now().toString()).put("label",label).put("seconds_requested",seconds)
                .put("foot","left").put("protocol_version",1).put("nominal_hz",104).put("firmware",firmware)
                .put("address",address).put("battery",battery).put("accel_g_per_lsb",.000244)
                .put("gyro_dps_per_lsb",.035).put("gyro_range_dps",1000).put("accel_range_g",8)
                .put("reference_spm",reference==null?JSONObject.NULL:reference)
                .put("speed_mph",speed==null?JSONObject.NULL:speed)
                .put("speed_kph",speed==null?JSONObject.NULL:speed*1.609344)
                .put("recording",true).put("completed",false).put("samples",0);
            if(reference!=null) metadata.put("reference_source","user_reported_count").put("reference_steps_scope","both_feet");
            save(directory,metadata);
            first=Files.newBufferedWriter(new File(directory,"imu.csv").toPath(),StandardCharsets.UTF_8);
            first.write("sequence,device_us,elapsed_us,received_utc,received_monotonic_ns,gx_raw,gy_raw,gz_raw,ax_raw,ay_raw,az_raw,gx_dps,gy_dps,gz_dps,ax_g,ay_g,az_g\n");
            second=Files.newBufferedWriter(new File(directory,"fit.csv").toPath(),StandardCharsets.UTF_8);
            second.write("sequence,elapsed_us,gyro_y_dps,gyro_filtered_dps,cadence_spm,stride\n");
        } catch(Exception e) {
            if(first!=null) first.close(); if(second!=null) second.close(); throw e;
        }
        imu=first; fit=second;
    }
    void append(Protocol.Sample s) throws Exception {
        long elapsed=window.append(s);
        if(lastUs>=0) { long interval=s.elapsedUs-lastUs; maxInterval=Math.max(maxInterval,interval); if(interval>20000) gaps++; }
        lastUs=s.elapsedUs;
        boolean saturated=false;
        StringBuilder row=new StringBuilder().append(s.sequence).append(',').append(s.deviceUs).append(',')
            .append(elapsed).append(',').append(Instant.now()).append(',').append(s.receivedNs);
        for(short v:s.raw) { row.append(',').append(v); saturated|=v==Short.MIN_VALUE || v==Short.MAX_VALUE; }
        if(saturated) clipped++;
        for(float v:s.gyro) row.append(',').append(String.format(Locale.US,"%.6f",v));
        for(float v:s.accel) row.append(',').append(String.format(Locale.US,"%.6f",v));
        imu.write(row.append('\n').toString());
        fit.write(String.format(Locale.US,"%d,%d,%.6f,%.6f,%.4f,%d\n",s.sequence,elapsed,s.gyro[1],s.filtered,s.fitted,s.stride?1:0));
        if(window.samples%100==0) { imu.flush(); fit.flush(); checkpoint(); }
    }
    private void checkpoint() throws Exception {
        metadata.put("samples",window.samples).put("missing_packets",window.missing)
            .put("device_duration_s",window.duration()).put("clipped_samples",clipped)
            .put("timing_gaps_over_20ms",gaps).put("max_interval_us",maxInterval);
        if(window.duration()>0) metadata.put("received_hz",(window.samples-1)/window.duration());
        save(directory,metadata);
    }
    void finish(String error, boolean stopped) throws Exception {
        IOException closeError=null;
        try { imu.close(); } catch(IOException e) { closeError=e; }
        try { fit.close(); } catch(IOException e) { closeError=e; }
        if(closeError!=null && error==null) error="Storage error: "+closeError.getMessage();
        metadata.put("recording",false).put("completed",error==null && window.samples>=2)
            .put("stopped_by_user",stopped).put("ended_utc",Instant.now().toString());
        if(error!=null) metadata.put("error",error);
        checkpoint();
    }
    static void recover(Context c) {
        File[] directories=root(c).listFiles(File::isDirectory);
        if(directories==null) return;
        for(File d:directories) try {
            JSONObject m=read(d);
            if(m.optBoolean("recording")) {
                m.put("recording",false).put("completed",false).put("error","App stopped before the recording finished; partial files retained");
                save(d,m);
            }
        } catch(Exception ignored) { /* Keep raw files even if metadata is damaged. */ }
    }
    static File export(Context c,File directory) throws Exception {
        if(!directory.getCanonicalFile().getParentFile().equals(root(c).getCanonicalFile())) throw new SecurityException("Invalid session");
        JSONObject m=read(directory);
        if(m.optBoolean("recording")) throw new IOException("Stop recording before exporting");
        File exports=new File(c.getFilesDir(),"exports");
        if(!exports.isDirectory() && !exports.mkdirs()) throw new IOException("Cannot create export folder");
        File output=new File(exports,directory.getName()+".zip"), temp=new File(exports,directory.getName()+".tmp");
        try(ZipOutputStream zip=new ZipOutputStream(new FileOutputStream(temp))) {
            for(String name:new String[]{"imu.csv","fit.csv","session.json"}) {
                File f=new File(directory,name); if(!f.isFile()) continue;
                zip.putNextEntry(new ZipEntry(name)); Files.copy(f.toPath(),zip); zip.closeEntry();
            }
        }
        Files.move(temp.toPath(),output.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        return output;
    }
}
