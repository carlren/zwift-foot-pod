package com.carlren.footpod;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import org.json.JSONObject;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
import java.util.zip.*;

/** Device-side storage check. Synthetic packets remain in test code, outside the delivered APK. */
public final class TestProbe extends Instrumentation {
    private void check(boolean ok) { if(!ok) throw new AssertionError(); }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        Bundle result=new Bundle(); List<File> created=new ArrayList<>();
        try {
            Context c=getTargetContext(); long now=SystemClock.elapsedRealtimeNanos();
            JSONObject battery=new JSONObject().put("voltage_v",3.9).put("percent",72);
            Session s=new Session(c,"device-storage-check",3,null,2.0,"test-only","0.4.0",battery,now); created.add(s.directory);
            Protocol.Decoder decoder=new Protocol.Decoder(); Protocol.Detector fit=new Protocol.Detector();
            for(int i=0;i<300;i++) {
                int sequence=i+(i>=150?1:0);
                ByteBuffer b=ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN).putInt(sequence).putInt(i*10000);
                for(int raw:new int[]{0,(int)(4000*Math.sin(i*.06)),0,0,0,4096}) b.putShort((short)raw);
                Protocol.Sample sample=decoder.decode(b.array(),now+i*10000000L);
                sample.stride=fit.update(sample.gyro[1],sample.deviceUs); sample.filtered=fit.filtered; sample.fitted=fit.cadence(sample.deviceUs);
                s.append(sample);
            }
            check(Session.read(s.directory).getBoolean("recording"));
            s.finish(null,false); JSONObject m=Session.read(s.directory);
            check(m.getBoolean("completed") && !m.getBoolean("recording") && m.getLong("samples")==300);
            check(m.getLong("missing_packets")==1 && Math.abs(m.getDouble("device_duration_s")-2.99)<.0001);
            check(Files.readAllLines(new File(s.directory,"imu.csv").toPath()).size()==301);
            check(Files.readAllLines(new File(s.directory,"fit.csv").toPath()).size()==301);
            m.put("reference_total_steps",5).put("reference_spm",5*60/m.getDouble("device_duration_s")); Session.save(s.directory,m);
            File zip=Session.export(c,s.directory); created.add(zip);
            try(ZipFile archive=new ZipFile(zip)) {
                check(archive.size()==3 && archive.getEntry("imu.csv")!=null && archive.getEntry("fit.csv")!=null);
                JSONObject exported=new JSONObject(new String(archive.getInputStream(archive.getEntry("session.json")).readAllBytes(),StandardCharsets.UTF_8));
                check(exported.getInt("reference_total_steps")==5);
            }
            Uri uri=new Uri.Builder().scheme("content").authority("com.carlren.footpod.sessions").appendPath(zip.getName()).build();
            try(InputStream input=c.getContentResolver().openInputStream(uri)) { check(input!=null && input.read()=='P' && input.read()=='K'); }
            Uri invalid=new Uri.Builder().scheme("content").authority("com.carlren.footpod.sessions").appendPath("../outside.zip").build();
            try { c.getContentResolver().openInputStream(invalid); throw new AssertionError("Traversal accepted"); } catch(FileNotFoundException expected) {}
            Session partial=new Session(c,"partial-check",3,null,null,"test-only","0.4.0",battery,now); created.add(partial.directory);
            partial.finish("Bluetooth disconnected",true);
            check(!Session.read(partial.directory).getBoolean("completed") && Session.read(partial.directory).has("error"));
            JSONObject interrupted=Session.read(partial.directory); interrupted.put("recording",true); Session.save(partial.directory,interrupted);
            Session.recover(c); check(!Session.read(partial.directory).getBoolean("recording") && !Session.read(partial.directory).getBoolean("completed"));
            result.putString("stream","PASS: real Android CSV/fit/metadata, reference edit, ZIP, read-only URI, traversal rejection, partial and interrupted recording recovery\n");
            finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {
            StringWriter output=new StringWriter(); error.printStackTrace(new PrintWriter(output)); result.putString("stream","FAIL: "+output);
            finish(Activity.RESULT_CANCELED,result);
        } finally {
            for(File file:created) {
                if(file.isDirectory()) { File[] children=file.listFiles(); if(children!=null) for(File child:children) child.delete(); }
                file.delete();
            }
        }
    }
}
