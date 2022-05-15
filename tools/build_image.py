import sys
from pathlib import Path
import os
import subprocess

'''
Build docker image with the local files in asobann_app and push to AWS ECR (Container Registry).

% cd deploy/tools  # actually it can run from anywhere
% python3 build_image.py

Notes:
- Invokes AWS CLI command internally.
- ECR URI is embedded.
'''

config = {

}

def system(cmd, capture=False, cwd=None, daemon=False):
    if capture:
        stdout = subprocess.PIPE
    else:
        stdout = None
    if daemon:
        proc = subprocess.Popen(cmd,
                                shell=True,
                                stdout=stdout,
                                stderr=subprocess.STDOUT,
                                cwd=cwd,
                                encoding='utf8')
        return proc
    else:
        proc = subprocess.run(cmd,
                              shell=True,
                              stdout=stdout,
                              stderr=subprocess.STDOUT,
                              cwd=cwd,
                              encoding='utf8')
        if proc.returncode != 0:
            raise RuntimeError(f'external command "{cmd}" failed. output="{proc.stdout}"')
        return proc


def build_docker_image():
    os.chdir(config['REPO_APP_DIR'])
    system('pipenv lock -r > requirements.txt')
    system('docker build -f Dockerfile.aws -t asobann_aws:latest .')


def push_docker_image():
    system('docker tag asobann_aws:latest 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws:latest')
    system('aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws')
    system('docker push 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws:latest')


def build_latest():
    build_docker_image()
    push_docker_image()


def tag_latest_as_production():
    system('docker tag asobann_aws:latest 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws:production')
    system('aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws')
    system('docker push 550251267268.dkr.ecr.us-east-1.amazonaws.com/asobann_aws:production')


def main():
    arg = sys.argv[1:]
    if len(arg) < 1:
        cmd = 'build_latest'
    else:
        cmd = arg[0]

    if cmd == 'build_latest':
        build_latest()
    elif cmd == 'tag_latest_as_production':
        tag_latest_as_production()


if __name__=='__main__':
    config['REPO_APP_DIR'] = (Path(__file__).absolute().parent.parent.parent / 'asobann_app').absolute()
    main()
