import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface ComputeStackProps extends cdk.StackProps {
  stage: string;
  bucket: s3.IBucket;
  connectionsTable: dynamodb.ITable;
}

export class ComputeStack extends cdk.Stack {
  public readonly dataParserFunction: lambda.Function;
  public readonly aiInsightFunction: lambda.Function;
  public readonly qualityCheckerFunction: lambda.Function;
  public readonly deliveryFunction: lambda.Function;
  public readonly ecsCluster: ecs.Cluster;
  public readonly reportGeneratorTaskDef: ecs.FargateTaskDefinition;

  constructor(scope: Construct, id: string, props: ComputeStackProps) {
    super(scope, id, props);

    const projectRoot = path.join(__dirname, '..', '..');

    // Lambda code asset — pre-installed deps in ./lib directory
    const lambdaCode = lambda.Code.fromAsset(projectRoot, {
      exclude: [
        'infra',
        'infra/**',
        '**/node_modules',
        '**/node_modules/**',
        '.venv',
        '.venv/**',
        'tests',
        'tests/**',
        '.git',
        '.git/**',
        'cdk.out',
        'cdk.out/**',
        '*.tar.gz',
        '__pycache__',
        '**/__pycache__',
      ],
    });

    // Common Lambda environment
    const commonEnv: { [key: string]: string } = {
      S3_BUCKET_NAME: props.bucket.bucketName,
      DYNAMODB_CONNECTIONS_TABLE: props.connectionsTable.tableName,
      BEDROCK_MODEL_ID: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
      BEDROCK_REGION: 'us-east-1',
      BEDROCK_MAX_RPS: '0.9',
      STAGE: props.stage,
    };

    // Common Lambda policy for Bedrock
    const bedrockPolicy = new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:Converse'],
      resources: ['*'],
    });

    // === Lambda Functions ===

    // Module 1: Data Parser
    this.dataParserFunction = new lambda.Function(this, 'DataParser', {
      functionName: `smart-report-data-parser-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'src.modules.data_parser.handler.handler',
      code: lambdaCode,
      memorySize: 1024,
      timeout: cdk.Duration.minutes(5),
      environment: commonEnv,
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });
    props.bucket.grantReadWrite(this.dataParserFunction);
    props.connectionsTable.grantReadWriteData(this.dataParserFunction);

    // Module 2: AI Insight
    this.aiInsightFunction = new lambda.Function(this, 'AIInsight', {
      functionName: `smart-report-ai-insight-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'src.modules.ai_insight.handler.handler',
      code: lambdaCode,
      memorySize: 2048,
      timeout: cdk.Duration.minutes(10),
      environment: commonEnv,
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });
    props.bucket.grantReadWrite(this.aiInsightFunction);
    props.connectionsTable.grantReadWriteData(this.aiInsightFunction);
    this.aiInsightFunction.addToRolePolicy(bedrockPolicy);

    // Module 4: Quality Checker
    this.qualityCheckerFunction = new lambda.Function(this, 'QualityChecker', {
      functionName: `smart-report-quality-checker-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'src.modules.quality_checker.handler.handler',
      code: lambdaCode,
      memorySize: 1024,
      timeout: cdk.Duration.minutes(3),
      environment: commonEnv,
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });
    props.bucket.grantReadWrite(this.qualityCheckerFunction);
    props.connectionsTable.grantReadWriteData(this.qualityCheckerFunction);

    // Module 5: Delivery
    this.deliveryFunction = new lambda.Function(this, 'Delivery', {
      functionName: `smart-report-delivery-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'src.modules.delivery.handler.handler',
      code: lambdaCode,
      memorySize: 512,
      timeout: cdk.Duration.minutes(3),
      environment: {
        ...commonEnv,
        SES_SENDER_EMAIL: 'noreply@smartreport.example.com',
      },
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });
    props.bucket.grantRead(this.deliveryFunction);
    props.connectionsTable.grantReadWriteData(this.deliveryFunction);
    this.deliveryFunction.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ses:SendRawEmail', 'ses:SendEmail'],
      resources: ['*'],
    }));

    // === ECS Fargate (Module 3: Report Generator) ===

    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
    });

    this.ecsCluster = new ecs.Cluster(this, 'EcsCluster', {
      clusterName: `smart-report-${props.stage}`,
      vpc,
    });

    this.reportGeneratorTaskDef = new ecs.FargateTaskDefinition(this, 'ReportGenTask', {
      memoryLimitMiB: 4096,
      cpu: 2048,
    });

    props.bucket.grantReadWrite(this.reportGeneratorTaskDef.taskRole);
    props.connectionsTable.grantReadWriteData(this.reportGeneratorTaskDef.taskRole);

    // Use a simple placeholder image for now (will be replaced with actual build)
    this.reportGeneratorTaskDef.addContainer('report-generator', {
      image: ecs.ContainerImage.fromRegistry('python:3.12-slim'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'report-gen',
        logRetention: logs.RetentionDays.TWO_WEEKS,
      }),
      environment: commonEnv,
      command: ['echo', 'placeholder - replace with actual image'],
    });

    // Outputs
    new cdk.CfnOutput(this, 'EcsClusterName', { value: this.ecsCluster.clusterName });
  }
}
