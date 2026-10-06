"""Compile the actual board detector on the host and check it against saved reference IMU data."""
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile

from dashboard import Detector

ROOT=Path(__file__).resolve().parent
RUNNER=r'''
#include <iostream>
#include <iomanip>
#include "cadence.h"
int main() {
  GyroCadence detector;
  uint32_t t; int raw_y;
  std::cout << std::setprecision(9);
  while (std::cin >> t >> raw_y) {
    bool event=detector.update(raw_y*0.035f,t);
    std::cout << detector.spm << ' ' << int(detector.cadence(t)) << ' '
              << event << ' ' << detector.cycles << '\n';
  }
}
'''


def run(executable, frames):
    result=subprocess.run([str(executable)],input=''.join(f'{t} {raw}\n' for t,raw in frames),
                          text=True,capture_output=True,check=True,timeout=30)
    return [line.split() for line in result.stdout.splitlines()]


def main():
    report={'result':'PASS','detector':'footpod/cadence.h','recordings':[]}
    with tempfile.TemporaryDirectory() as directory:
        cpp=Path(directory)/'runner.cpp';cpp.write_text(RUNNER)
        exe=Path(directory)/'runner'
        subprocess.run(['g++','-std=c++11','-O2','-I',str(ROOT/'footpod'),str(cpp),'-o',str(exe)],check=True)
        for spm in (70,92,110,180):
            frames=[(i*10000,round(150*math.sin(2*math.pi*(i/100)/(120/spm))/.035)) for i in range(2000)]
            rows=run(exe,frames)
            assert abs(float(rows[-1][0])-spm)<2
            wrapped=run(exe,[((t+0xFFFFFF00)&0xFFFFFFFF,raw) for t,raw in frames])
            assert rows==wrapped,'Microsecond rollover changed the estimate'
        frames=[(i*10000,3000) for i in range(1000)]
        assert all(row[2]=='0' for row in run(exe,frames)), 'Constant rotation caused strides'
        frames=[(i*10000,round(150*math.sin(2*math.pi*i/100)/.035)) for i in range(1000)]
        frames.extend([(10_000_000+i*10000,0) for i in range(400)])
        assert run(exe,frames)[-1][1]=='0','Cadence did not return to zero after stopping'
        for path in sorted((ROOT/'recordings').glob('*/session.json')):
            metadata=json.loads(path.read_text())
            if metadata.get('reference_source')!='user_reported_count' or metadata.get('exclude_from_training'):
                continue
            with (path.parent/'imu.csv').open() as source:data=list(csv.DictReader(source))
            frames=[(int(r['elapsed_us'])&0xFFFFFFFF,int(r['gy_raw'])) for r in data]
            cpp_rows=run(exe,frames)
            python=Detector();values=[];max_difference=0
            for original,compiled in zip(data,cpp_rows):
                t=int(original['elapsed_us'])/1e6
                fit=python.update(dict(time_s=t,
                    gyro=[float(original[k]) for k in ('gx_dps','gy_dps','gz_dps')],
                    accel=[float(original[k]) for k in ('ax_g','ay_g','az_g')]))
                assert int(compiled[2])==int(fit['strike']),'Firmware/dashboard cycle decisions differ'
                max_difference=max(max_difference,abs(float(compiled[0])-fit['cadence']))
                if t>=5 and int(compiled[1])>0:values.append(float(compiled[0]))
            mean=round(statistics.mean(values),2)
            assert max_difference<.05
            assert abs(mean-metadata['reference_spm'])<2
            result=dict(recording=str(path.parent),reference_spm=metadata['reference_spm'],
                        mean_firmware_spm=mean,cycles=int(cpp_rows[-1][3]),
                        max_difference_from_dashboard=max_difference)
            report['recordings'].append(result)
            print(json.dumps(result),flush=True)
        assert len(report['recordings'])>=5
    report['synthetic_checks']='70/92/110/180 spm, microsecond rollover, stationary rotation, stop timeout'
    (ROOT/'validation/firmware-algorithm-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: actual C++ board detector matches the dashboard and all reference recordings')


if __name__=='__main__':
    main()
