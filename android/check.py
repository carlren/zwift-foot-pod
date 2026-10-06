"""Run the APK's actual Java decoder/detector/timer code against malformed packets and reference walks."""
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from dashboard import Detector

JAVA=r'''
package com.carlren.footpod;
import java.nio.*;
import java.util.*;
public class Check {
    static void check(boolean ok) { if(!ok) throw new AssertionError(); }
    static byte[] packet(long seq,long us) {
        ByteBuffer b=ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt((int)seq).putInt((int)us); for(int v:new int[]{-32768,32767,-1,0,1,4096}) b.putShort((short)v);
        return b.array();
    }
    static void rejects(Runnable f) { try { f.run(); } catch(IllegalArgumentException expected) { return; } throw new AssertionError("Malformed input accepted"); }
    static void selfCheck() {
        Protocol.Decoder d=new Protocol.Decoder();
        Protocol.Sample a=d.decode(packet(0xffffffffL,0xffffff00L),1000000000L);
        Protocol.Sample b=d.decode(packet(0,9744),1010000000L);
        check(b.elapsedUs==10000 && b.missing==0 && a.raw[0]==-32768 && a.raw[1]==32767);
        check(Math.abs(a.accel[2]-.999424f)<.00001);
        Protocol.Sample c=d.decode(packet(2,29744),1030000000L); check(c.missing==1);
        rejects(()->d.decode(new byte[19],0));
        rejects(()->d.decode(packet(2,29744),0));
        rejects(()->Protocol.percent(new byte[]{101})); rejects(()->Protocol.cadence(new byte[5]));
        check(Protocol.cadence(new byte[]{0,0,0,(byte)255})==255);
        rejects(()->Protocol.status(new byte[16]));
        byte[] status=new byte[16]; status[0]=1; status[1]=7; status[2]=0x6a;
        check(Protocol.status(status)[0]==7); status[1]=8; rejects(()->Protocol.status(status));
        rejects(()->Protocol.voltage(new byte[7]));
        Protocol.RecordingWindow w=new Protocol.RecordingWindow(1000000000L,60);
        a.receivedNs=999999999L; check(!w.accepts(a));
        a.receivedNs=1000000000L; check(w.accepts(a)); check(w.append(a)==0);
        b.receivedNs=60999999999L; b.elapsedUs=60000000L; check(w.append(b)==60000000L);
        check(w.duration()==60 && w.reference(70)==70 && w.remaining(31000000000L)==30);
        c.receivedNs=61000000000L; check(!w.accepts(c)); rejects(()->w.append(c));
        check(w.remaining(999999999999L)==0); rejects(()->new Protocol.RecordingWindow(0,Double.NaN));
        rejects(()->new Protocol.RecordingWindow(0,0)); rejects(()->new Protocol.RecordingWindow(0,3601));
        for(int target:new int[]{70,92,110,180}) {
            Protocol.Detector fit=new Protocol.Detector(),wrap=new Protocol.Detector();
            for(int i=0;i<2000;i++) {
                float gy=(float)(150*Math.sin(2*Math.PI*i/100/(120.0/target)));
                long us=i*10000L;
                check(fit.update(gy,us)==wrap.update(gy,(us+0xffffff00L)&0xffffffffL));
                check(Math.abs(fit.spm-wrap.spm)<.01);
            }
            check(Math.abs(fit.spm-target)<2);
            for(int i=2000;i<2400;i++) fit.update(0,i*10000L);
            check(fit.cadence(23990000L)==0);
        }
        Protocol.Detector constant=new Protocol.Detector();
        for(int i=0;i<1000;i++) check(!constant.update(100,i*10000L));
    }
    public static void main(String[] args) {
        selfCheck();
        if(args.length==0) { System.out.println("PASS: packet validation, unsigned wrapping, gaps, record boundaries, countdown, reference, gyro and stop"); return; }
        Scanner input=new Scanner(System.in); Protocol.Detector fit=new Protocol.Detector();
        while(input.hasNextLong()) {
            long us=input.nextLong(); int raw=input.nextInt(); boolean stride=fit.update(raw*.035f,us);
            System.out.printf(Locale.ROOT,"%.9f %d %d%n",fit.spm,stride?1:0,fit.cadence(us));
        }
    }
}
'''

def main():
    java=Path.home()/'android-dev/jdk-17/bin'
    source=ROOT/'android/app/src/main/java/com/carlren/footpod/Protocol.java'
    report=dict(result='PASS',host_checks='Decoder validation, unsigned clocks/sequence, recording boundaries/countdown, reference, synthetic cadence and stop',recordings=[])
    with tempfile.TemporaryDirectory() as temp:
        check=Path(temp)/'Check.java'; check.write_text(JAVA)
        subprocess.run([str(java/'javac'),'-d',temp,str(source),str(check)],check=True)
        cmd=[str(java/'java'),'-cp',temp,'com.carlren.footpod.Check']
        subprocess.run(cmd,check=True)
        for session in sorted((ROOT/'recordings').glob('*/session.json')):
            metadata=json.loads(session.read_text())
            if metadata.get('reference_source')!='user_reported_count' or metadata.get('exclude_from_training'): continue
            with (session.parent/'imu.csv').open() as handle: data=list(csv.DictReader(handle))
            frames=''.join(f"{int(r['elapsed_us'])&0xffffffff} {r['gy_raw']}\n" for r in data)
            output=subprocess.run(cmd+['replay'],input=frames,text=True,capture_output=True,check=True,timeout=40)
            results=[line.split() for line in output.stdout.splitlines()]
            assert len(results)==len(data)
            host=Detector(); values=[]; difference=0
            for original,compiled in zip(data,results):
                t=int(original['elapsed_us'])/1e6
                fit=host.update(dict(time_s=t,gyro=[float(original[k]) for k in ('gx_dps','gy_dps','gz_dps')],accel=[float(original[k]) for k in ('ax_g','ay_g','az_g')]))
                assert int(compiled[1])==int(fit['strike']), 'Android/firmware stride decisions differ'
                difference=max(difference,abs(float(compiled[0])-fit['cadence']))
                if t>=5 and int(compiled[2])>0: values.append(float(compiled[0]))
            mean=statistics.mean(values)
            assert difference<.05 and abs(mean-metadata['reference_spm'])<2
            report['recordings'].append(dict(recording=session.parent.name,reference_spm=metadata['reference_spm'],mean_android_spm=round(mean,2),max_fit_difference=difference))
        assert len(report['recordings'])>=5
    (ROOT/'validation/android-protocol-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: actual Android gyro detector matches all five walking references')

if __name__=='__main__': main()
