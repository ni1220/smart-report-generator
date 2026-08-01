#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { StorageStack } from '../lib/storage-stack';
import { ComputeStack } from '../lib/compute-stack';
import { ApiStack } from '../lib/api-stack';
import { WorkflowStack } from '../lib/workflow-stack';
import { MonitoringStack } from '../lib/monitoring-stack';

const app = new cdk.App();
const stage = app.node.tryGetContext('stage') || 'dev';

// Competition requirement: deploy to us-east-1
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: 'us-east-1',
};

const storageStack = new StorageStack(app, `SmartReport-Storage-${stage}`, {
  env,
  stage,
});

const computeStack = new ComputeStack(app, `SmartReport-Compute-${stage}`, {
  env,
  stage,
  bucket: storageStack.bucket,
  connectionsTable: storageStack.connectionsTable,
});

const workflowStack = new WorkflowStack(app, `SmartReport-Workflow-${stage}`, {
  env,
  stage,
  bucket: storageStack.bucket,
  dataParserFunction: computeStack.dataParserFunction,
  aiInsightFunction: computeStack.aiInsightFunction,
  qualityCheckerFunction: computeStack.qualityCheckerFunction,
  deliveryFunction: computeStack.deliveryFunction,
  reportGeneratorCluster: computeStack.ecsCluster,
  reportGeneratorTaskDef: computeStack.reportGeneratorTaskDef,
});

const apiStack = new ApiStack(app, `SmartReport-API-${stage}`, {
  env,
  stage,
  stateMachine: workflowStack.stateMachine,
  bucket: storageStack.bucket,
});

const monitoringStack = new MonitoringStack(app, `SmartReport-Monitoring-${stage}`, {
  env,
  stage,
  stateMachine: workflowStack.stateMachine,
  apiGateway: apiStack.api,
});

// Tags
cdk.Tags.of(app).add('Project', 'SmartReportGenerator');
cdk.Tags.of(app).add('Stage', stage);
cdk.Tags.of(app).add('Competition', '2026-GenAI-Hackathon');
