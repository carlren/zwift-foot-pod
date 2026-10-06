"""Replay a saved IMU session through the current gyro prototype, preserving its original fit."""
import argparse
import csv
import json
from pathlib import Path
import statistics

from dashboard import Detector, settings


def replay(directory, axis='y'):
    directory=Path(directory)
    metadata=json.loads((directory/'session.json').read_text())
    config=settings({'axis':axis})
    detector=Detector(**config)
    cadence=[]
    with (directory/'imu.csv').open() as source,(directory/'gyro_fit.csv').open('w',newline='') as output:
        writer=csv.writer(output)
        writer.writerow(['sequence','time_s','gyro_axis','gyro_raw_dps','gyro_filtered_dps',
                         'acceleration_magnitude_g','stride_event','cadence_spm'])
        for row in csv.DictReader(source):
            t=int(row['elapsed_us'])/1e6
            fit=detector.update(dict(time_s=t,
                gyro=[float(row[k]) for k in ('gx_dps','gy_dps','gz_dps')],
                accel=[float(row[k]) for k in ('ax_g','ay_g','az_g')]))
            writer.writerow([row['sequence'],t,axis,fit['gyro_signal'],fit['gyro_filtered'],
                             fit['magnitude'],int(fit['strike']),fit['cadence']])
            if t>=5 and fit['cadence']>0:
                cadence.append(fit['cadence'])
    summary=dict(algorithm='signed-gyro-cycle-prototype-v1',settings=config,
        recording=str(directory),duration_s=metadata['device_duration_s'],stride_cycles=detector.strikes,
        warmup_excluded_s=5,mean_cadence_spm=round(statistics.mean(cadence),2) if cadence else None,
        median_cadence_spm=round(statistics.median(cadence),2) if cadence else None,
        reference_spm=metadata.get('reference_spm'),reference_spm_range=metadata.get('reference_spm_range'),
        reference_speed_entered=metadata.get('reference_speed_entered'))
    (directory/'gyro-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--axis',choices=('x','y','z'),default='y')
    args=parser.parse_args()
    print(json.dumps(replay(args.directory,args.axis),indent=2))
