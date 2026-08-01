#!/bin/bash
#
# 智匯數據簡報神器 — 部署驗證腳本
# 用法: ./scripts/verify_deployment.sh [stage]
#
# 此腳本會依序驗證：
# 1. AWS 連線與身份
# 2. CDK Stack 部署狀態
# 3. API Health Check
# 4. Cognito 認證
# 5. 報告生成端到端測試
# 6. 產出品質驗證
#

set -euo pipefail

# === 設定 ===
STAGE="${1:-dev}"
REGION="us-east-1"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() { echo -e "${GREEN}✓ PASS${NC}: $1"; }
fail() { echo -e "${RED}✗ FAIL${NC}: $1"; exit 1; }
warn() { echo -e "${YELLOW}⚠ WARN${NC}: $1"; }
info() { echo -e "  ℹ $1"; }

echo "======================================"
echo " 智匯數據簡報神器 — 部署驗證"
echo " Stage: ${STAGE} | Region: ${REGION}"
echo "======================================"
echo ""

# === Step 1: AWS 連線驗證 ===
echo "--- Step 1: AWS 連線驗證 ---"

IDENTITY=$(aws sts get-caller-identity --region $REGION --output json 2>/dev/null) || fail "無法連線 AWS，請確認 credentials"
ACCOUNT_ID=$(echo $IDENTITY | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
pass "AWS 連線成功 (Account: $ACCOUNT_ID)"

# === Step 2: CDK Stack 狀態 ===
echo ""
echo "--- Step 2: CDK Stack 部署狀態 ---"

STACKS=(
  "SmartReport-Storage-${STAGE}"
  "SmartReport-Compute-${STAGE}"
  "SmartReport-Workflow-${STAGE}"
  "SmartReport-API-${STAGE}"
  "SmartReport-Monitoring-${STAGE}"
)

ALL_DEPLOYED=true
for STACK in "${STACKS[@]}"; do
  STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK" --region $REGION \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || STATUS="NOT_FOUND"
  
  if [[ "$STATUS" == "CREATE_COMPLETE" || "$STATUS" == "UPDATE_COMPLETE" ]]; then
    pass "$STACK ($STATUS)"
  elif [[ "$STATUS" == "NOT_FOUND" ]]; then
    warn "$STACK 尚未部署"
    ALL_DEPLOYED=false
  else
    warn "$STACK 狀態異常: $STATUS"
    ALL_DEPLOYED=false
  fi
done

if [[ "$ALL_DEPLOYED" != "true" ]]; then
  echo ""
  warn "部分 Stack 未部署，後續測試可能失敗"
  echo "  執行: cd infra && npx cdk deploy --all --context stage=${STAGE}"
  echo ""
fi

# === Step 3: 取得 Stack Outputs ===
echo ""
echo "--- Step 3: 取得部署資訊 ---"

get_output() {
  local stack=$1 key=$2
  aws cloudformation describe-stacks --stack-name "$stack" --region $REGION \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue" --output text 2>/dev/null || echo ""
}

API_URL=$(get_output "SmartReport-API-${STAGE}" "ApiUrl")
USER_POOL_ID=$(get_output "SmartReport-API-${STAGE}" "UserPoolId")
CLIENT_ID=$(get_output "SmartReport-API-${STAGE}" "UserPoolClientId")
BUCKET=$(get_output "SmartReport-Storage-${STAGE}" "BucketName")
SFN_ARN=$(get_output "SmartReport-Workflow-${STAGE}" "StateMachineArn")

if [[ -z "$API_URL" ]]; then
  warn "無法取得 API URL，跳過 API 測試"
  echo ""
  echo "======================================"
  echo " 部署驗證結果：部分通過（Stack 未完全部署）"
  echo "======================================"
  exit 0
fi

info "API URL: $API_URL"
info "User Pool: $USER_POOL_ID"
info "Bucket: $BUCKET"
info "StateMachine: $SFN_ARN"
pass "Stack Outputs 取得成功"

# === Step 4: API Health Check ===
echo ""
echo "--- Step 4: API Health Check ---"

HEALTH=$(curl -s "${API_URL}" 2>/dev/null) || fail "API 無回應"
STATUS=$(echo $HEALTH | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)

if [[ "$STATUS" == "healthy" ]]; then
  pass "API Health Check 通過"
else
  fail "API Health Check 失敗: $HEALTH"
fi

# 詳細 health
DETAIL=$(curl -s "${API_URL}health" 2>/dev/null)
info "Health detail: $DETAIL"

# === Step 5: Cognito 認證測試 ===
echo ""
echo "--- Step 5: Cognito 認證測試 ---"

# 嘗試取得 token
DEMO_USER="demo@hackathon.tw"
DEMO_PASS="DemoPass123!"

TOKEN=$(aws cognito-idp initiate-auth \
  --client-id "$CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters "Username=${DEMO_USER},Password=${DEMO_PASS}" \
  --query 'AuthenticationResult.IdToken' \
  --output text \
  --region $REGION 2>/dev/null) || TOKEN=""

if [[ -n "$TOKEN" && "$TOKEN" != "None" ]]; then
  pass "Cognito Token 取得成功"
else
  warn "Cognito 認證失敗（可能需要先建立 demo 用戶）"
  echo "  執行:"
  echo "  aws cognito-idp admin-create-user --user-pool-id $USER_POOL_ID --username $DEMO_USER --temporary-password TempPass1! --region $REGION"
  echo "  aws cognito-idp admin-set-user-password --user-pool-id $USER_POOL_ID --username $DEMO_USER --password $DEMO_PASS --permanent --region $REGION"
  echo ""
  echo "======================================"
  echo " 部署驗證結果：基礎設施通過，需建立測試用戶"
  echo "======================================"
  exit 0
fi

# === Step 6: S3 資料驗證 ===
echo ""
echo "--- Step 6: S3 資料驗證 ---"

# 檢查 bucket 存在且有 Block Public Access
BPA=$(aws s3api get-public-access-block --bucket "$BUCKET" --region $REGION \
  --query 'PublicAccessBlockConfiguration.BlockPublicAcls' --output text 2>/dev/null) || BPA="unknown"

if [[ "$BPA" == "True" ]]; then
  pass "S3 Block Public Access 已啟用（競賽合規）"
else
  warn "S3 Block Public Access 狀態: $BPA"
fi

# 檢查 sample data
SAMPLE_EXISTS=$(aws s3 ls "s3://${BUCKET}/sample_data/" --region $REGION 2>/dev/null | wc -l)
if [[ $SAMPLE_EXISTS -gt 0 ]]; then
  pass "Sample data 已上傳"
else
  warn "Sample data 未上傳，端到端測試會失敗"
  info "上傳: aws s3 cp sample_data/credit_card_stats_2025.xlsx s3://$BUCKET/sample_data/ --sse aws:kms --region $REGION"
fi

# === Step 7: 端到端報告生成測試 ===
echo ""
echo "--- Step 7: 端到端報告生成測試 ---"

if [[ $SAMPLE_EXISTS -eq 0 ]]; then
  warn "跳過端到端測試（缺少 sample data）"
else
  # 觸發報告生成
  RESPONSE=$(curl -s -X POST "${API_URL}api/v1/reports" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"data_source\": \"sample_data/credit_card_stats_2025.xlsx\",
      \"template\": \"default\",
      \"recipients\": [],
      \"options\": {\"language\": \"zh-TW\"}
    }" 2>/dev/null)

  TASK_ID=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_id',''))" 2>/dev/null)

  if [[ -n "$TASK_ID" ]]; then
    pass "報告生成已觸發 (task_id: $TASK_ID)"
    info "追蹤進度: curl ${API_URL}api/v1/reports/$TASK_ID -H 'Authorization: Bearer \$TOKEN'"

    # 等待並輪詢（最多 3 分鐘）
    echo "  等待執行中..."
    MAX_WAIT=180
    ELAPSED=0
    INTERVAL=10

    while [[ $ELAPSED -lt $MAX_WAIT ]]; do
      sleep $INTERVAL
      ELAPSED=$((ELAPSED + INTERVAL))

      STATUS_RESP=$(curl -s "${API_URL}api/v1/reports/$TASK_ID" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null)
      TASK_STATUS=$(echo $STATUS_RESP | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null)

      if [[ "$TASK_STATUS" == "completed" ]]; then
        pass "報告生成完成！(${ELAPSED}s)"
        
        # 檢查 outputs
        PPTX_URL=$(echo $STATUS_RESP | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('outputs',{}).get('pptx_url',''))" 2>/dev/null)
        if [[ -n "$PPTX_URL" ]]; then
          pass "PPTX 下載連結已生成"
        fi

        QA_PASSED=$(echo $STATUS_RESP | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('quality_score',{}).get('passed',''))" 2>/dev/null)
        if [[ "$QA_PASSED" == "True" ]]; then
          pass "品質檢驗通過"
        else
          warn "品質檢驗結果: $QA_PASSED"
        fi
        break
      elif [[ "$TASK_STATUS" == "failed" ]]; then
        fail "報告生成失敗 (${ELAPSED}s)"
      else
        echo -ne "  ... ${TASK_STATUS} (${ELAPSED}s)\r"
      fi
    done

    if [[ $ELAPSED -ge $MAX_WAIT ]]; then
      warn "等待逾時（${MAX_WAIT}s），請手動查看 Step Functions Console"
    fi
  else
    fail "觸發報告生成失敗: $RESPONSE"
  fi
fi

# === Step 8: Bedrock 模型存取驗證 ===
echo ""
echo "--- Step 8: Bedrock 模型存取驗證 ---"

MODEL_ACCESS=$(aws bedrock list-foundation-models --region $REGION \
  --query "modelSummaries[?modelId=='anthropic.claude-3-5-sonnet-20241022-v2:0'].modelId" \
  --output text 2>/dev/null) || MODEL_ACCESS=""

if [[ -n "$MODEL_ACCESS" ]]; then
  pass "Bedrock Claude 3.5 Sonnet 模型可存取"
else
  warn "無法確認 Bedrock 模型存取權，請至 Bedrock Console 申請"
fi

# === Step 9: 監控驗證 ===
echo ""
echo "--- Step 9: 監控 Dashboard 驗證 ---"

DASHBOARD=$(aws cloudwatch list-dashboards --region $REGION \
  --query "DashboardEntries[?DashboardName=='SmartReport-${STAGE}'].DashboardName" \
  --output text 2>/dev/null) || DASHBOARD=""

if [[ -n "$DASHBOARD" ]]; then
  pass "CloudWatch Dashboard 已建立"
  info "查看: https://console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=SmartReport-${STAGE}"
else
  warn "CloudWatch Dashboard 未找到"
fi

# === 總結 ===
echo ""
echo "======================================"
echo " 部署驗證完成"
echo "======================================"
echo ""
echo "有用的連結:"
echo "  API Docs:   ${API_URL}docs"
echo "  Dashboard:  https://console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=SmartReport-${STAGE}"
echo "  Step Fn:    https://console.aws.amazon.com/states/home?region=${REGION}#/statemachines/view/${SFN_ARN}"
echo "  S3 Bucket:  https://s3.console.aws.amazon.com/s3/buckets/${BUCKET}"
echo ""
