# 智匯數據簡報神器 — 系統設計

## 架構模式
非同步工作流 + 事件驅動，使用 AWS Step Functions 編排 5 步驟 pipeline。

## 元件設計

### API 層
- FastAPI + Mangum (Lambda adapter)
- API Gateway REST + WebSocket
- Cognito JWT Authorizer

### 工作流層
- AWS Step Functions (Standard workflow)
- 5 步驟：DataIngestion → AIInsight → ReportGen → QualityCheck → Delivery
- Choice state 做為品質閘門
- 失敗 catch → SNS 通知

### 運算層
- Lambda: 資料解析、AI 洞察、品質檢驗、寄發（輕量操作）
- ECS Fargate: 簡報生成（記憶體密集操作）

### AI 層
- Amazon Bedrock (Claude 3.5 Sonnet)
- 三段式生成 + Pydantic Schema 驗證
- Rate Limiter 確保 ≤ 1 RPS

### 儲存層
- S3: 模板、中間產物、最終產出（SSE-KMS 加密）
- DynamoDB: WebSocket 連線、Prompt 版本

### 監控層
- CloudWatch Dashboard + Alarms
- X-Ray 全鏈路追蹤

## 數據流

```
Excel(S3) → [Lambda] 解析驗證 → JSON(S3)
  → [Lambda] Bedrock 分段生成 → Plan JSON(S3)
  → [Fargate] PPTX+Excel 原生圖表渲染 → Files(S3)
  → [Lambda] 品質檢驗 → Pass/Fail
  → [Lambda] SES 寄信 + Presigned URL
```

## 安全設計
- 認證: Cognito User Pool + JWT
- 授權: API Gateway Usage Plan + Rate Limit
- 加密: S3 SSE-KMS, HTTPS in transit
- 網路: Fargate in Private Subnet, NAT Gateway
- 審計: CloudTrail API logging
