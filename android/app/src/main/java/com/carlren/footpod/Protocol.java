package com.carlren.footpod;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.UUID;
import java.util.Locale;

/** Firmware v1 wire protocol. No Android dependencies: checked against real CSV data. */
public final class Protocol {
    public static UUID custom(int n) { return UUID.fromString(String.format(Locale.ROOT,"e85b000%d-6d10-4a22-90c5-c813f72b1357", n)); }
    public static UUID standard(String n) { return UUID.fromString("0000"+n+"-0000-1000-8000-00805f9b34fb"); }
    public static final UUID SERVICE=custom(1), DATA=custom(2), CONTROL=custom(3), STATUS=custom(4), VOLTAGE=custom(5);
    public static final UUID LEVEL=standard("2a19"), CADENCE=standard("2a53"), FIRMWARE=standard("2a28"), CCCD=standard("2902");
    public static final class Sample {
        public long sequence, deviceUs, elapsedUs, receivedNs, missing;
        public final short[] raw=new short[6];
        public final float[] gyro=new float[3], accel=new float[3];
        public float filtered, fitted;
        public boolean stride;
    }
    public static final class Decoder {
        private long sequence=-1, deviceUs, elapsed, missing;
        public Sample decode(byte[] packet, long receivedNs) {
            if(packet.length!=20) throw new IllegalArgumentException("IMU packet must be 20 bytes");
            ByteBuffer b=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
            Sample s=new Sample(); s.sequence=Integer.toUnsignedLong(b.getInt()); s.deviceUs=Integer.toUnsignedLong(b.getInt());
            if(sequence!=-1) {
                long increment=(s.sequence-sequence)&0xffffffffL, interval=(s.deviceUs-deviceUs)&0xffffffffL;
                if(increment==0 || increment>=0x80000000L || interval==0 || interval>=3000000)
                    throw new IllegalArgumentException("Device clock reset, duplicate packet or a long data gap");
                elapsed+=interval; missing+=increment-1;
            }
            sequence=s.sequence; deviceUs=s.deviceUs; s.elapsedUs=elapsed; s.missing=missing; s.receivedNs=receivedNs;
            for(int i=0;i<6;i++) s.raw[i]=b.getShort();
            for(int i=0;i<3;i++) { s.gyro[i]=s.raw[i]*.035f; s.accel[i]=s.raw[i+3]*.000244f; }
            return s;
        }
    }
    public static final class Detector {
        public float filtered, spm;
        public long cycles;
        private long lastSample, lastStride;
        private boolean haveSample, haveStride, armed;
        public boolean update(float rotation, long us) {
            long dt=(us-lastSample)&0xffffffffL;
            if(!haveSample || dt==0 || dt>100000) { filtered=rotation; armed=false; }
            else filtered+=(1f-(float)Math.exp(-dt*.000001f/.04f))*(rotation-filtered);
            lastSample=us; haveSample=true;
            if(haveStride && ((us-lastStride)&0xffffffffL)>3000000) { haveStride=false; spm=0; armed=false; }
            if(filtered<=-20f) armed=true;
            if(!armed || filtered<40f) return false;
            armed=false;
            long interval=(us-lastStride)&0xffffffffL;
            if(haveStride && interval<450000) return false;
            if(haveStride) {
                float measured=120000000f/interval;
                spm=spm!=0 ? .6f*spm+.4f*measured : measured;
            }
            lastStride=us; haveStride=true; cycles++; return true;
        }
        public int cadence(long us) {
            return !haveStride || ((us-lastStride)&0xffffffffL)>3000000 ? 0 : Math.round(Math.min(255f,Math.max(0f,spm)));
        }
    }
    public static int cadence(byte[] packet) {
        if(packet.length!=4 || packet[0]!=0) throw new IllegalArgumentException("Unsupported RSC packet");
        return Byte.toUnsignedInt(packet[3]);
    }
    public static int percent(byte[] packet) {
        if(packet.length!=1 || Byte.toUnsignedInt(packet[0])>100) throw new IllegalArgumentException("Invalid battery percentage");
        return Byte.toUnsignedInt(packet[0]);
    }
    public static int[] voltage(byte[] packet) {
        if(packet.length!=6) throw new IllegalArgumentException("Invalid battery diagnostics");
        ByteBuffer b=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
        int[] r={Short.toUnsignedInt(b.getShort()),Short.toUnsignedInt(b.getShort()),Byte.toUnsignedInt(b.get()),Byte.toUnsignedInt(b.get())};
        if(r[0]>6000 || r[1]>4095 || r[2]>1 || r[3]>1) throw new IllegalArgumentException("Invalid battery values");
        return r;
    }
    public static long[] status(byte[] packet) {
        if(packet.length!=16 || packet[0]!=1 || (packet[1]&~7)!=0 || packet[3]!=0)
            throw new IllegalArgumentException("Unsupported collection protocol");
        ByteBuffer b=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
        b.position(4);
        return new long[]{Byte.toUnsignedInt(packet[1]),Byte.toUnsignedInt(packet[2]),Integer.toUnsignedLong(b.getInt()),Integer.toUnsignedLong(b.getInt()),Integer.toUnsignedLong(b.getInt())};
    }
    public static final class RecordingWindow {
        public final long startedNs, deadlineNs;
        public long firstUs=-1, lastUs, firstSequence, lastSequence, samples, missing;
        public RecordingWindow(long startedNs, double seconds) {
            if(!Double.isFinite(seconds) || seconds<1 || seconds>3600) throw new IllegalArgumentException("Duration must be 1–3600 seconds");
            this.startedNs=startedNs; deadlineNs=startedNs+(long)(seconds*1e9);
        }
        public boolean accepts(Sample s) { return s.receivedNs>=startedNs && s.receivedNs<deadlineNs; }
        public long append(Sample s) {
            if(!accepts(s)) throw new IllegalArgumentException("Sample outside recording window");
            if(firstUs<0) { firstUs=s.elapsedUs; firstSequence=s.sequence; }
            else missing+=((s.sequence-lastSequence)&0xffffffffL)-1;
            lastUs=s.elapsedUs; lastSequence=s.sequence; samples++; return lastUs-firstUs;
        }
        public double remaining(long nowNs) { return Math.max(0,(deadlineNs-nowNs)/1e9); }
        public double duration() { return samples<2 ? 0 : (lastUs-firstUs)/1e6; }
        public double reference(int totalSteps) {
            if(totalSteps<=0 || duration()<=0) throw new IllegalArgumentException("Enter a positive step count for a completed recording");
            return totalSteps*60/duration();
        }
    }
}
