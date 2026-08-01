import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';

export interface StorageStackProps extends cdk.StackProps {
  stage: string;
}

export class StorageStack extends cdk.Stack {
  public readonly bucket: s3.Bucket;
  public readonly connectionsTable: dynamodb.Table;
  public readonly promptsTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, props);

    // KMS key for S3 encryption
    const kmsKey = new kms.Key(this, 'BucketKey', {
      alias: `smart-report-${props.stage}`,
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // S3 Bucket — competition requirement: Block Public Access
    this.bucket = new s3.Bucket(this, 'ReportBucket', {
      bucketName: `smart-report-${props.stage}-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, // Competition requirement
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      versioned: false,
      lifecycleRules: [
        {
          id: 'cleanup-artifacts',
          prefix: 'tasks/',
          expiration: cdk.Duration.days(30),
        },
      ],
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          maxAge: 3600,
        },
      ],
    });

    // DynamoDB: WebSocket connections
    this.connectionsTable = new dynamodb.Table(this, 'ConnectionsTable', {
      tableName: `ws-connections-${props.stage}`,
      partitionKey: { name: 'connection_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'ttl',
    });

    this.connectionsTable.addGlobalSecondaryIndex({
      indexName: 'task-id-index',
      partitionKey: { name: 'task_id', type: dynamodb.AttributeType.STRING },
    });

    // DynamoDB: Prompt versions
    this.promptsTable = new dynamodb.Table(this, 'PromptsTable', {
      tableName: `prompt-versions-${props.stage}`,
      partitionKey: { name: 'prompt_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'version', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Outputs
    new cdk.CfnOutput(this, 'BucketName', { value: this.bucket.bucketName });
    new cdk.CfnOutput(this, 'ConnectionsTableName', { value: this.connectionsTable.tableName });
  }
}
