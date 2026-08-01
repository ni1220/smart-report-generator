import * as cdk from 'aws-cdk-lib';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

export interface WorkflowStackProps extends cdk.StackProps {
  stage: string;
  bucket: s3.IBucket;
  dataParserFunction: lambda.IFunction;
  aiInsightFunction: lambda.IFunction;
  qualityCheckerFunction: lambda.IFunction;
  deliveryFunction: lambda.IFunction;
  reportGeneratorCluster: ecs.ICluster;
  reportGeneratorTaskDef: ecs.FargateTaskDefinition;
}

export class WorkflowStack extends cdk.Stack {
  public readonly stateMachine: sfn.StateMachine;

  constructor(scope: Construct, id: string, props: WorkflowStackProps) {
    super(scope, id, props);

    // SNS Topic for failure alerts
    const alertTopic = new sns.Topic(this, 'AlertTopic', {
      topicName: `smart-report-alerts-${props.stage}`,
    });

    // === Step Functions States ===

    // Step 1: Data Ingestion
    const dataIngestion = new tasks.LambdaInvoke(this, 'DataIngestion', {
      lambdaFunction: props.dataParserFunction,
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    });
    dataIngestion.addRetry({
      errors: ['States.ALL'],
      maxAttempts: 2,
      backoffRate: 2,
    });

    // Step 2: AI Insight Generation
    const aiInsightGeneration = new tasks.LambdaInvoke(this, 'AIInsightGeneration', {
      lambdaFunction: props.aiInsightFunction,
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    });
    aiInsightGeneration.addRetry({
      errors: ['BedrockThrottling'],
      maxAttempts: 3,
      backoffRate: 3,
    });

    // Step 3: Report Generation (ECS Fargate)
    const reportGeneration = new tasks.EcsRunTask(this, 'ReportGeneration', {
      integrationPattern: sfn.IntegrationPattern.RUN_JOB,
      cluster: props.reportGeneratorCluster,
      taskDefinition: props.reportGeneratorTaskDef,
      launchTarget: new tasks.EcsFargateLaunchTarget(),
      containerOverrides: [
        {
          containerDefinition: props.reportGeneratorTaskDef.defaultContainer!,
          environment: [
            { name: 'TASK_ID', value: sfn.JsonPath.stringAt('$.task_id') },
            { name: 'PRESENTATION_PLAN_KEY', value: sfn.JsonPath.stringAt('$.presentation_plan_key') },
            { name: 'TEMPLATE_NAME', value: 'default' },
          ],
        },
      ],
      resultPath: '$.ecsResult',
    });

    // Step 4: Quality Check
    const qualityCheck = new tasks.LambdaInvoke(this, 'QualityCheck', {
      lambdaFunction: props.qualityCheckerFunction,
      outputPath: '$.Payload',
    });

    // Step 5: Send Report
    const sendReport = new tasks.LambdaInvoke(this, 'SendReport', {
      lambdaFunction: props.deliveryFunction,
      outputPath: '$.Payload',
    });

    // Failure notification
    const notifyFailure = new tasks.SnsPublish(this, 'NotifyFailure', {
      topic: alertTopic,
      message: sfn.TaskInput.fromText('Report generation failed'),
      subject: '[SmartReport] Pipeline Failure',
    });

    const failState = new sfn.Fail(this, 'Failed', {
      cause: 'Report generation pipeline failed',
    });

    const successState = new sfn.Succeed(this, 'Success');

    // Quality gate choice
    const qualityGate = new sfn.Choice(this, 'QualityGate')
      .when(
        sfn.Condition.booleanEquals('$.quality.passed', true),
        sendReport.next(successState)
      )
      .otherwise(
        new sfn.Choice(this, 'RetryOrFail')
          .when(
            sfn.Condition.numberLessThan('$.retryCount', 2),
            new sfn.Pass(this, 'IncrementRetry', {
              parameters: {
                'task_id.$': '$.task_id',
                'parsed_data_key.$': '$.parsed_data_key',
                'retryCount.$': sfn.JsonPath.mathAdd(sfn.JsonPath.numberAt('$.retryCount'), 1),
              },
            }).next(aiInsightGeneration)
          )
          .otherwise(notifyFailure.next(failState))
      );

    // === Chain ===
    const definition = dataIngestion
      .next(aiInsightGeneration)
      .next(reportGeneration)
      .next(qualityCheck)
      .next(qualityGate);

    // Add error catching
    dataIngestion.addCatch(notifyFailure, { resultPath: '$.error' });
    aiInsightGeneration.addCatch(notifyFailure, { resultPath: '$.error' });
    reportGeneration.addCatch(notifyFailure, { resultPath: '$.error' });

    // State Machine
    this.stateMachine = new sfn.StateMachine(this, 'ReportPipeline', {
      stateMachineName: `smart-report-pipeline-${props.stage}`,
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.minutes(15),
      tracingEnabled: true, // X-Ray tracing
      logs: {
        destination: new logs.LogGroup(this, 'SfnLogs', {
          logGroupName: `/aws/stepfunctions/smart-report-${props.stage}`,
          retention: logs.RetentionDays.TWO_WEEKS,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        level: sfn.LogLevel.ALL,
      },
    });

    // Outputs
    new cdk.CfnOutput(this, 'StateMachineArn', { value: this.stateMachine.stateMachineArn });
    new cdk.CfnOutput(this, 'AlertTopicArn', { value: alertTopic.topicArn });
  }
}
