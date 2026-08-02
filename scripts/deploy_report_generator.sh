#!/bin/bash
#
# 部署 Report Generator Lambda（含 speaker notes 修復）
# 在 AWS CloudShell 中執行
#
# 用法: bash deploy_report_generator.sh
#

set -e

FUNCTION_NAME="smart-report-report-generator-dev"
S3_BUCKET="smart-report-dev-866373558659"
S3_KEY="lambda-packages/report-generator-latest.zip"
REGION="us-east-1"
GITHUB_RAW="https://raw.githubusercontent.com/ni1220/smart-report-generator/main"

echo "=== 開始部署 Report Generator Lambda ==="
echo "Function: $FUNCTION_NAME"
echo ""

# Clean workspace
rm -rf /tmp/report-gen-deploy
mkdir -p /tmp/report-gen-deploy/package
cd /tmp/report-gen-deploy

# 1. Download source files from GitHub
echo "[1/5] 下載最新原始碼..."
mkdir -p package/src/modules/report_generator
mkdir -p package/src/modules/ai_insight
mkdir -p package/src/shared

# Root __init__.py files
curl -sL "$GITHUB_RAW/src/__init__.py" -o package/src/__init__.py
curl -sL "$GITHUB_RAW/src/modules/__init__.py" -o package/src/modules/__init__.py

# Report Generator module
curl -sL "$GITHUB_RAW/src/modules/report_generator/__init__.py" -o package/src/modules/report_generator/__init__.py
curl -sL "$GITHUB_RAW/src/modules/report_generator/lambda_handler.py" -o package/src/modules/report_generator/lambda_handler.py
curl -sL "$GITHUB_RAW/src/modules/report_generator/pptx_engine.py" -o package/src/modules/report_generator/pptx_engine.py
curl -sL "$GITHUB_RAW/src/modules/report_generator/xlsx_engine.py" -o package/src/modules/report_generator/xlsx_engine.py
curl -sL "$GITHUB_RAW/src/modules/report_generator/template_loader.py" -o package/src/modules/report_generator/template_loader.py
curl -sL "$GITHUB_RAW/src/modules/report_generator/main.py" -o package/src/modules/report_generator/main.py

# AI Insight models (needed for PresentationPlan import)
curl -sL "$GITHUB_RAW/src/modules/ai_insight/__init__.py" -o package/src/modules/ai_insight/__init__.py
curl -sL "$GITHUB_RAW/src/modules/ai_insight/models.py" -o package/src/modules/ai_insight/models.py

# Shared modules
curl -sL "$GITHUB_RAW/src/shared/__init__.py" -o package/src/shared/__init__.py
curl -sL "$GITHUB_RAW/src/shared/config.py" -o package/src/shared/config.py
curl -sL "$GITHUB_RAW/src/shared/s3_utils.py" -o package/src/shared/s3_utils.py
curl -sL "$GITHUB_RAW/src/shared/websocket_notifier.py" -o package/src/shared/websocket_notifier.py

echo "  ✓ 原始碼下載完成"

# Verify pptx_engine.py downloaded correctly
if grep -q "PptxGenerator" package/src/modules/report_generator/pptx_engine.py; then
    echo "  ✓ 確認 pptx_engine.py 下載正確"
else
    echo "  ✗ 錯誤：pptx_engine.py 下載失敗！"
    exit 1
fi

# 2. Install dependencies
echo ""
echo "[2/5] 安裝 Python 依賴套件..."
pip install \
  --platform manylinux2014_x86_64 \
  --target package/ \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  python-pptx==1.0.2 openpyxl==3.1.5 pydantic==2.10.3 lxml -q
echo "  ✓ 依賴套件安裝完成"

# 3. Create ZIP
echo ""
echo "[3/5] 打包 Lambda 部署包..."
cd package
zip -r9 /tmp/report-gen-deploy/lambda.zip . -q
cd ..
ZIP_SIZE=$(du -h /tmp/report-gen-deploy/lambda.zip | cut -f1)
echo "  ✓ ZIP 打包完成 (大小: $ZIP_SIZE)"

# 4. Upload to S3
echo ""
echo "[4/5] 上傳到 S3..."
aws s3 cp /tmp/report-gen-deploy/lambda.zip "s3://$S3_BUCKET/$S3_KEY" --region $REGION
echo "  ✓ 上傳完成: s3://$S3_BUCKET/$S3_KEY"

# 5. Update Lambda function code
echo ""
echo "[5/5] 更新 Lambda 函數..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --s3-bucket "$S3_BUCKET" \
    --s3-key "$S3_KEY" \
    --region $REGION \
    --no-cli-pager

# Wait for update to complete
echo "  等待更新完成..."
aws lambda wait function-updated --function-name "$FUNCTION_NAME" --region $REGION 2>/dev/null || sleep 5

# Verify handler configuration
echo ""
echo "=== 驗證 Lambda 設定 ==="
HANDLER=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region $REGION --query 'Handler' --output text 2>/dev/null)
LAST_MOD=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" --region $REGION --query 'LastModified' --output text 2>/dev/null)
echo "  Handler: $HANDLER"
echo "  Last Modified: $LAST_MOD"

# Ensure handler is correct
EXPECTED_HANDLER="src.modules.report_generator.lambda_handler.handler"
if [ "$HANDLER" != "$EXPECTED_HANDLER" ]; then
    echo "  ⚠️  Handler 不正確！正在修正..."
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --handler "$EXPECTED_HANDLER" \
        --region $REGION \
        --no-cli-pager
    echo "  ✓ Handler 已更正為: $EXPECTED_HANDLER"
else
    echo "  ✓ Handler 正確"
fi

echo ""
echo "=== ✅ 部署完成！ ==="
echo ""
echo "驗證指令："
echo "  aws lambda get-function-configuration --function-name $FUNCTION_NAME --region $REGION --query '[LastModified, Handler]' --output text"
echo ""
echo "測試生成報告後，下載 PPTX 並在 PowerPoint 中查看「備忘稿」(Notes) 面板。"
echo ""
echo "查看日誌（確認 notes 是否寫入）："
echo "  aws logs tail /aws/lambda/$FUNCTION_NAME --region $REGION --since 5m --filter-pattern 'Speaker notes'"
