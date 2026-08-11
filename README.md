Deploy [asobann](https://github.com/yattom/asobann_app) to AWS ECS with CloudFormation.


## Limitations
- Table data will be retained upon deployment, updating stacks, and / or restarting tasks or instances.
- Kit data will be initialized upon each deployment.
- EBS volume will be created and used to persist table data between deployments.
- S3 bucket will be created and used for image storage.
- You need a domain and https certificate to be available on Route53.
- This deployment will not fit within AWS free tier, or so I think.
- EC2 instance type is fixed to t3.small.

## Prerequisite

- Python >= 3.6 and pip is installed.
- AWS CLI installed and set up.
- node >= v14 is installed.
- Checked out asobann ```https://github.com/yattom/asobann_app``` already.
- Checked out this repository.

## How to deploy

0. Make sure development environment is setup.  (Do this when library configuration is updated.)

   ```shell script
   % cd /path/to/asobann
   % pnpm install
   ```

   Install [uv](https://docs.astral.sh/uv/) for Python dependency management.

1. Build asobann image and push to ECR.

   ```shell script
   % cd /path/to/asobann_app
   % pnpm exec webpack
   % uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt
   % docker build -f Dockerfile.aws -t asobann_aws:latest .
   % docker tag asobann_aws 999999999999.dkr.ecr.REGION.amazonaws.com/asobann_aws
   % aws ecr get-login-password --region REGION | docker login --username AWS --password-stdin \
       999999999999.dkr.ecr.REGION.amazonaws.com/asobann_aws
   % docker push 999999999999.dkr.ecr.REGION.amazonaws.com/asobann_aws
   ```

   Replace 999999999999 with your AWS account id and REGION with region name to deploy (e.g. us-east-1)

1. Deploy with CloudFromation

   ```shell script
   % cd /path/to/asobann_deploy
   % cd aws_dev
   % aws cloudformation package --template-file asobann_aws.yaml --s3-bucket CFN_BUCKET_NAME --s3-prefix dev \
       --output-template-file OUTPUT_TEMPLATE_FILE
   Uploading to xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.template  2500 / 2500.0  (100.00%)
   Successfully packaged artifacts and wrote output template to file /tmp/asobann_aws.yaml.
   Execute the following command to deploy the packaged template
   aws cloudformation deploy --template-file /tmp/asobann_aws.yaml --stack-name <YOUR STACK NAME>

   % aws cloudformation deploy --template-file OUTPUT_TEMPLATE_FILE --stack-name asobann-dev \
       --parameter-overrides PublicHostname=dev.asobann.example.com \
       MaintenanceIpRange=<SSH_IP> MongoDbPassword=senSiblPssw0rd \
       AppImage=999999999999.dkr.ecr.REGION.amazonaws.com/asobann_aws \
       AppTaskCount=1 CertificateArn=<Certificate ARN> GoogleAnalyticsId=NotAvailable \
       UploadedImageStore=s3 AwsKey=<AWS_KEY> AwsSecret=<AWS_SECRET> FlaskEnv=development \
       DebugOpts=LOG \
       --capabilities CAPABILITY_IAM
   Waiting for changeset to be created..
   Waiting for stack create/update to complete
   Successfully created/updated stack - asobann-dev
   ```

    Replace CFN_BUCKET_NAME with a S3 bucket to put CloudFormation templates.  Maybe you need to create one.
    
    Replace OUTPUT_TEMPLATE_FILE for temporarily used template file to deploy.  I prefer /tmp/asobann_aws_dev.yaml
    
    You need to specify parameters.
    
    - PublicHostname: Service hostname.  You can access the service with this name.  Domain must be already registered in Route53.  (_Hostname registration is screwed in the template in the time being.  Please be careful and do the patching by yourself._)
    - \<SSH_IP\>: CIDR block for ssh connection.  Set IP range of your own PC like 1.2.3.4/24.  Set 10.0.0.0/16 to prevent ssh from outside. (I hope it works.)
    - MongoDbPassword: admin user of MongoDB will be created with this password.  Use a sensible one but MongoDB will not be exposed to the internet.
    - \<Certificate ARN\>: Certificate arn to use for https
    - AppImage: image of asobann you just pushed in step 1.
    - AppTaskCount: Desired task number for app service.  Default is 3.
    - GoogleAnalyticsId: Google Analytics ID like UA-000000000-0.  Disabled in development mode.
    - UploadedImageStore: Where uploaded images are stored.  Either ***s3*** or ***local***.  Default to local.  Local storage will be cleared when restarting app service.
    - \<AWS_KEY\>, \<AWS_SECRET\>: AWS Key and secret for app to access S3 bucket.
    - FlaskEnv: Either **development** or **production**.  Default to production.
    - DebugOpts: Comma separated list of debug options.  See asobann_app/src/asobann/config_dev.py.  FLASK_ENV must be development for debug options to work.
    
1. Access created service.  Get Service URL from outputs in created stacks.  Access from Web AWS Console, or awscli as below.

   Execute command below and look for "ServiceUrl' in Output section of LoadBalancer Stack part
   
    ```shell script
    % aws cloudformation describe-stacks
    ...
        {
            "OutputKey": "ServiceUrl",
            "OutputValue": "http://asoba-LoadB-XXXXXXXXXXXXX-9999999999.us-east-1.elb.amazonaws.com",
            "Description": "URL of the load balancer for the sample service."
        },
    ...
    ```
   
   Access the url and you will see deployed asobann.

### Sample alias

I set and use shell aliases like this:

```shell script
alias build_aws=' \
  # run from asobann_app dir
  set -x ; \
  pnpm exec webpack ; \
  docker build -f Dockerfile.aws -t asobann_aws:latest . ; \
  docker tag asobann_aws 999999999999.dkr.ecr.us-east-1.amazonaws.com/asobann_aws ; \
  aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 999999999999.dkr.ecr.us-east-1.amazonaws.com/asobann_aws ; \
  docker push 999999999999.dkr.ecr.us-east-1.amazonaws.com/asobann_aws ; \
  set +x'
alias cfn_deploy_dev=' \
  # run from asobann_deploy/aws dir
  set -x ; \
  aws cloudformation package --template-file asobann_aws.yaml --s3-bucket YOURBUCKETNAME --s3-prefix dev --output-template-file /tmp/asobann_aws.yaml ;
  aws cloudformation deploy --template-file /tmp/asobann_aws.yaml --stack-name asobann-dev --parameter-overrides PublicHostname=dev.asobann.example.com MaintenanceIpRange=192.0.2.0/24 MongoDbPassword=LAMEPASSWORD AppImage=999999999999.dkr.ecr.us-east-1.amazonaws.com/asobann_aws AppTaskCount=1 CertificateArn=arn:aws:acm:us-east-1:999999999999:certificate/blahblahblah GoogleAnalyticsId=NotAvailable --capabilities CAPABILITY_IAM --tags ProjectName=asobann AsobannEnv=dev; \
  set +x'
alias cfn_deploy_prod=' \
  # run from asobann_deploy/aws dir
  set -x ; \
  aws cloudformation package --template-file asobann_aws.yaml --s3-bucket YOURBUCKETNAME --s3-prefix prod --output-template-file /tmp/asobann_aws.yaml ;
  aws cloudformation deploy --template-file /tmp/asobann_aws.yaml --stack-name asobann-prod --parameter-overrides PublicHostname=asobann.example.com MaintenanceIpRange=192.0.2.0/24 MongoDbPassword=SERIOUSPASSWORD AppImage=999999999999.dkr.ecr.us-east-1.amazonaws.com/asobann_aws AppTaskCount=3 CertificateArn=arn:aws:acm:us-east-1:999999999999:certificate/blahblahblah GoogleAnalyticsId=UA-000000000-0 --capabilities CAPABILITY_IAM --tags ProjectName=asobann AsobannEnv=prod ; \
  set +x'
```
