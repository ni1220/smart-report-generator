#!/bin/bash
#
# 診斷 Speaker Notes 問題
# 在 AWS CloudShell 中執行
#

REGION="us-east-1"
FUNCTION_NAME="smart-report-report-generator-dev"
SFN_ARN="arn:aws:states:us-east-1:866373558659:stateMachine:smart-report-pipeline-dev"

echo "=== 診斷 Speaker Notes 問題 ==="
echo ""

# 1. Check Lambda configuration
echo "[1] Lambda 函數設定"
echo "---"
aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region $REGION \
    --query '{Handler: Handler, Runtime: Runtime, LastModified: LastModified, CodeSize: CodeSize, MemorySize: MemorySize, Timeout: Timeout}' \
    --output table --no-cli-pager 2>/dev/null || echo "  ❌ Lambda 函數不存在！"
echo ""

# 2. Check Step Functions definition for ReportGeneration step
echo "[2] Step Functions 定義 (ReportGeneration 步驟)"
echo "---"
aws stepfunctions describe-state-machine \
    --state-machine-arn "$SFN_ARN" \
    --region $REGION \
    --query 'definition' \
    --output text --no-cli-pager 2>/dev/null | python3 -c "
import sys, json
try:
    defn = json.loads(sys.stdin.read())
    states = defn.get('States', {})
    for name, state in states.items():
        if 'Report' in name or 'report' in name:
            print(f'  State: {name}')
            print(f'  Type: {state.get(\"Type\")}')
            resource = state.get('Resource', 'N/A')
            print(f'  Resource: {resource}')
            params = state.get('Parameters', {})
            if params:
                print(f'  Parameters: {json.dumps(params, indent=4, ensure_ascii=False)[:500]}')
            result_path = state.get('ResultPath', 'N/A')
            print(f'  ResultPath: {result_path}')
            print()
except Exception as e:
    print(f'  Error parsing: {e}')
"
echo ""

# 3. Check recent Lambda logs for the report generator
echo "[3] 最近的 Report Generator Lambda 日誌"
echo "---"
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"
aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region $REGION --query 'logGroups[0].logGroupName' --output text --no-cli-pager 2>/dev/null
if [ $? -eq 0 ]; then
    echo "  最近 30 分鐘日誌："
    aws logs tail "$LOG_GROUP" --region $REGION --since 30m --no-cli-pager 2>/dev/null | grep -i -E "speaker|notes|v2\\.1|pptx_engine|Failed|Error|generate" | head -20
    if [ $? -ne 0 ]; then
        echo "  (無相關日誌 - Lambda 可能未被呼叫)"
    fi
else
    echo "  ❌ 日誌群組不存在 - Lambda 可能從未被執行過"
fi
echo ""

# 4. Check most recent Step Functions execution
echo "[4] 最近一次 Step Functions 執行"
echo "---"
EXEC_ARN=$(aws stepfunctions list-executions \
    --state-machine-arn "$SFN_ARN" \
    --region $REGION \
    --max-results 1 \
    --query 'executions[0].executionArn' \
    --output text --no-cli-pager 2>/dev/null)

if [ -n "$EXEC_ARN" ] && [ "$EXEC_ARN" != "None" ]; then
    echo "  Execution: $EXEC_ARN"
    STATUS=$(aws stepfunctions describe-execution \
        --execution-arn "$EXEC_ARN" \
        --region $REGION \
        --query 'status' --output text --no-cli-pager)
    echo "  Status: $STATUS"
    
    # Get execution history for ReportGeneration step
    echo ""
    echo "  ReportGeneration 步驟歷史："
    aws stepfunctions get-execution-history \
        --execution-arn "$EXEC_ARN" \
        --region $REGION \
        --query "events[?contains(to_string(@), 'Report') || contains(to_string(@), 'report')]" \
        --output json --no-cli-pager 2>/dev/null | python3 -c "
import sys, json
try:
    events = json.loads(sys.stdin.read())
    for ev in events[:5]:
        etype = ev.get('type', '')
        print(f'    {etype}')
        details = ev.get('lambdaFunctionScheduledEventDetails') or ev.get('taskScheduledEventDetails') or ev.get('lambdaFunctionSucceededEventDetails') or {}
        if details:
            resource = details.get('resource', details.get('resourceType', ''))
            if resource:
                print(f'      Resource: {resource}')
            inp = details.get('input', '')
            if inp:
                try:
                    d = json.loads(inp)
                    print(f'      Input keys: {list(d.keys())}')
                except:
                    pass
except Exception as e:
    print(f'    Parse error: {e}')
"
else
    echo "  ❌ 無執行記錄"
fi

echo ""
echo "=== 診斷完成 ==="
echo ""
echo "常見問題："
echo "  1. Step Functions 仍使用 ECS Fargate 而非 Lambda → 需更新 SFN 定義"
echo "  2. Lambda handler 路徑不正確 → 應為 src.modules.report_generator.lambda_handler.handler"
echo "  3. Lambda 代碼過舊 → 執行 deploy_report_generator.sh 重新部署"
echo "  4. 日誌顯示 'v2.1' → 代碼已更新，問題在其他地方"
