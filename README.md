# 智匯數據簡報神器 (Smart Report Generator)

2026 雲湧智生：臺灣生成式 AI 應用黑客松競賽 — 台新新光金控命題

## 專案簡介

AI 驅動的自動化系統，讀取 1-12 月信用卡業務統計資料，透過 Amazon Bedrock (Claude 3.5 Sonnet) 進行策略顧問級分析，產出 16 頁原生可編輯簡報 + 同步 Excel 資料檔。

## 核心特色

- **原生可編輯圖表**：PPT/Excel 圖表為向量原生物件，非圖片貼上
- **非同步工作流**：Step Functions 編排，WebSocket 即時進度回饋
- **品質自動檢驗**：QA Gate 確保產出品質
- **全 AWS 原生架構**：部署於 us-east-1，符合競賽規範

## 快速開始

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動本地開發伺服器
uvicorn src.api.main:app --reload --port 8000

# 執行測試
pytest tests/ -v
```

## 部署

```bash
cd infra && npm install
cdk deploy --all --context stage=dev --region us-east-1
```

## 架構

詳見 `Kiro_Implementation_Guide_v2.md`

## 競賽合規

- 部署區域：us-east-1
- Bedrock RPS：≤ 1（Rate Limiter 控制）
- S3：Block Public Access 啟用
- `.kiro/` 資料夾保留展示 Kiro 使用情況
