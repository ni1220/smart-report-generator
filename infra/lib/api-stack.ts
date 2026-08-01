import * as cdk from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface ApiStackProps extends cdk.StackProps {
  stage: string;
  stateMachine: sfn.IStateMachine;
  bucket: s3.IBucket;
}

export class ApiStack extends cdk.Stack {
  public readonly api: apigateway.RestApi;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const projectRoot = path.join(__dirname, '..', '..');

    // === Cognito User Pool ===
    const userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `smart-report-users-${props.stage}`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      passwordPolicy: {
        minLength: 8,
        requireUppercase: true,
        requireDigits: true,
      },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const userPoolClient = userPool.addClient('WebClient', {
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      generateSecret: false,
    });

    // Cognito Authorizer
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, 'Authorizer', {
      cognitoUserPools: [userPool],
    });

    // === API Lambda Handler ===
    const apiHandler = new lambda.Function(this, 'ApiHandler', {
      functionName: `smart-report-api-${props.stage}`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'src.api.main.handler',
      code: lambda.Code.fromAsset(projectRoot, {
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
      }),
      memorySize: 512,
      timeout: cdk.Duration.seconds(29),
      environment: {
        S3_BUCKET_NAME: props.bucket.bucketName,
        STATE_MACHINE_ARN: props.stateMachine.stateMachineArn,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
        BEDROCK_MODEL_ID: 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        BEDROCK_REGION: 'us-east-1',
        STAGE: props.stage,
      },
      logRetention: logs.RetentionDays.TWO_WEEKS,
    });

    // Permissions
    props.bucket.grantRead(apiHandler);
    props.stateMachine.grantStartExecution(apiHandler);
    props.stateMachine.grantRead(apiHandler);
    apiHandler.addToRolePolicy(new iam.PolicyStatement({
      actions: ['states:ListExecutions', 'states:DescribeExecution', 'states:StopExecution'],
      resources: [props.stateMachine.stateMachineArn],
    }));

    // === API Gateway ===
    this.api = new apigateway.RestApi(this, 'Api', {
      restApiName: `smart-report-api-${props.stage}`,
      description: 'Smart Report Generator API',
      deployOptions: {
        stageName: props.stage,
        tracingEnabled: true,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
      },
    });

    // Usage Plan (Rate Limiting)
    const usagePlan = this.api.addUsagePlan('UsagePlan', {
      name: `smart-report-plan-${props.stage}`,
      throttle: {
        rateLimit: 10,
        burstLimit: 20,
      },
      quota: {
        limit: 1000,
        period: apigateway.Period.DAY,
      },
    });

    const apiKey = this.api.addApiKey('ApiKey', {
      apiKeyName: `smart-report-key-${props.stage}`,
    });
    usagePlan.addApiKey(apiKey);
    usagePlan.addApiStage({ stage: this.api.deploymentStage });

    // Proxy integration
    const integration = new apigateway.LambdaIntegration(apiHandler);

    // Routes
    const apiResource = this.api.root.addResource('api');
    const v1 = apiResource.addResource('v1');

    const reports = v1.addResource('reports');
    reports.addMethod('POST', integration, {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
    });

    const reportTask = reports.addResource('{task_id}');
    reportTask.addMethod('GET', integration, {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
    });
    reportTask.addMethod('DELETE', integration, {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
    });

    const templates = v1.addResource('templates');
    templates.addMethod('GET', integration, {
      authorizer,
      authorizationType: apigateway.AuthorizationType.COGNITO,
    });

    // Health (no auth)
    this.api.root.addMethod('GET', integration);
    this.api.root.addResource('health').addMethod('GET', integration);

    // Outputs
    new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
    new cdk.CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, 'ApiKeyId', { value: apiKey.keyId });
  }
}
