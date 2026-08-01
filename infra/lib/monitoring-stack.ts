import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import { Construct } from 'constructs';

export interface MonitoringStackProps extends cdk.StackProps {
  stage: string;
  stateMachine: sfn.IStateMachine;
  apiGateway: apigateway.RestApi;
}

export class MonitoringStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MonitoringStackProps) {
    super(scope, id, props);

    // Alert topic
    const alertTopic = new sns.Topic(this, 'MonitoringAlerts', {
      topicName: `smart-report-monitoring-${props.stage}`,
    });

    // === CloudWatch Dashboard ===
    const dashboard = new cloudwatch.Dashboard(this, 'Dashboard', {
      dashboardName: `SmartReport-${props.stage}`,
    });

    // Step Functions metrics
    const sfnSucceeded = props.stateMachine.metricSucceeded();
    const sfnFailed = props.stateMachine.metricFailed();
    const sfnDuration = props.stateMachine.metricTime();

    // API Gateway metrics
    const apiRequests = props.apiGateway.metricCount();
    const apiLatency = props.apiGateway.metricLatency();
    const api4xx = props.apiGateway.metricClientError();
    const api5xx = props.apiGateway.metricServerError();

    // Dashboard widgets
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: '工作流成功/失敗率',
        left: [sfnSucceeded],
        right: [sfnFailed],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: '工作流平均耗時',
        left: [sfnDuration],
        width: 12,
      }),
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API 請求量',
        left: [apiRequests],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'API 延遲 (ms)',
        left: [apiLatency],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: 'API 錯誤率',
        left: [api4xx, api5xx],
        width: 8,
      }),
    );

    // === Alarms ===＄＃

    // High failure rate
    new cloudwatch.Alarm(this, 'HighFailureRate', {
      alarmName: `SmartReport-HighFailureRate-${props.stage}`,
      metric: sfnFailed,
      threshold: 3,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Step Functions failure count > 3 in 5 minutes',
    });

    // API 5xx errors
    new cloudwatch.Alarm(this, 'Api5xxAlarm', {
      alarmName: `SmartReport-Api5xx-${props.stage}`,
      metric: api5xx,
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'API 5xx errors > 5 in 5 minutes',
    });

    // Long execution time
    new cloudwatch.Alarm(this, 'LongExecution', {
      alarmName: `SmartReport-LongExecution-${props.stage}`,
      metric: sfnDuration.with({ statistic: 'Maximum' }),
      threshold: 600000, // 10 minutes in ms
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      alarmDescription: 'Execution time > 10 minutes',
    });

    // Outputs
    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=${dashboard.dashboardName}`,
    });
  }
}
