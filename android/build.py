"""Build a signed personal APK; keep its reusable signing key outside the repository."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent

def main():
    env = os.environ.copy()
    env['JAVA_HOME'] = env.get('JAVA_HOME') or str(Path.home()/'android-dev/jdk-17')
    sdk = Path(env.get('ANDROID_HOME') or Path.home()/'android-dev/android-sdk')
    env['ANDROID_HOME'] = str(sdk)
    env['PATH'] = str(Path(env['JAVA_HOME'])/'bin')+os.pathsep+env['PATH']
    gradle = str(ROOT/'gradlew') if (ROOT/'gradlew').exists() else shutil.which('gradle') or str(Path.home()/'android-dev/gradle-8.10.2/bin/gradle')
    key_dir = Path.home()/'.local/share/foot-pod-lab'
    key_dir.mkdir(mode=0o700, exist_ok=True)
    key_dir.chmod(0o700)
    key = key_dir/'signing.jks'
    password_path = key_dir/'signing-password'
    if not password_path.exists():
        if key.exists():
            raise RuntimeError('Signing key exists but its password file is missing; preserve the existing key')
        descriptor = os.open(password_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(descriptor,'w') as handle:
            handle.write(secrets.token_urlsafe(36))
    password_path.chmod(0o600)
    env['FOOT_POD_KEY_PASSWORD'] = password_path.read_text().strip()
    env['FOOT_POD_KEYSTORE'] = str(key)
    if not key.exists():
        subprocess.run(['keytool','-genkeypair','-keystore',str(key),'-alias','footpod',
            '-storepass:env','FOOT_POD_KEY_PASSWORD','-keypass:env','FOOT_POD_KEY_PASSWORD',
            '-keyalg','RSA','-keysize','3072','-validity','10000',
            '-dname','CN=Carl Foot Pod Lab, OU=Personal, O=Carl, C=US'],env=env,check=True)
        key.chmod(0o600)
    (ROOT/'local.properties').write_text('sdk.dir='+str(sdk)+'\n')
    subprocess.run([gradle,'--no-daemon','assembleRelease','lintRelease'],cwd=ROOT,env=env,check=True)
    apk = ROOT/'app/build/outputs/apk/release/app-release.apk'
    signer = sdk/'build-tools/35.0.0/apksigner'
    subprocess.run([str(signer),'verify','--verbose',str(apk)],env=env,check=True)
    output = ROOT/'dist'; output.mkdir(exist_ok=True)
    version = json.loads((apk.parent/'output-metadata.json').read_text())['elements'][0]['versionName']
    destination = output/f'Foot-Pod-Lab-{version}.apk'
    shutil.copyfile(apk,destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output/'SHA256SUMS.txt').write_text(digest+'  '+destination.name+'\n')
    print('Signed APK:',destination)
    print('SHA256:',digest)

if __name__=='__main__':
    main()
