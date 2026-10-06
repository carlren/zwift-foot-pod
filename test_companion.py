"""Check the actual firmware's two-client state and LiPo interpolation on the host."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
CHECK = r'''
#include <cassert>
#include "companion.h"
int main() {
  PodClients clients;
  clients.connect(7); clients.connect(19);
  auto* zwift = clients.find(7); auto* phone = clients.find(19);
  assert(zwift && phone && zwift != phone);
  phone->collecting = true; phone->sent = 100;
  zwift->cadencePending = true;
  clients.connect(21); assert(!clients.find(21));
  clients.connect(19); assert(phone->sent == 100);
  phone->collecting = false;
  assert(zwift->cadencePending);
  phone->collecting = true;
  clients.disconnect(19);
  assert(!clients.find(19) && clients.find(7)->cadencePending);
  clients.connect(21);
  assert(!clients.find(21)->collecting && clients.find(21)->sent == 0);
  clients.find(21)->collecting = true;
  clients.disconnect(7); assert(clients.find(21)->collecting);
  assert(!clients.find(0xffff));
  assert(batteryPercent(0) == 0 && batteryPercent(3306) == 0);
  assert(batteryPercent(3821) == 50 && batteryPercent(4177) == 100);
  assert(batteryPercent(65535) == 100);
  for (unsigned mv = 1; mv < 65536; ++mv) {
    assert(batteryPercent(mv) >= batteryPercent(mv-1));
    assert(batteryPercent(mv) <= 100);
  }
}
'''

def main():
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'check.cpp'
        source.write_text(CHECK)
        executable = Path(directory) / 'check'
        subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'footpod'), str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
    print('PASS: two-client isolation, reconnect reset, capacity, battery curve/clamping')

if __name__ == '__main__':
    main()
