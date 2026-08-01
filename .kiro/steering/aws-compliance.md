---
inclusion: auto
---
# AWS Competition Compliance Rules

## Mandatory Rules (違反可能導致取消資格)

1. **Region**: 所有服務必須部署於 `us-east-1` 或 `us-west-2`
2. **S3**: 必須使用 Block Public Access，禁止公開 bucket
3. **Bedrock RPS**: 請求頻率必須 ≤ 1 RPS（使用 BedrockRateLimiter）
4. **Bedrock Models**: 僅申請必要模型（Claude 3.5 Sonnet + Titan Embeddings）
5. **No EC2 Public SG**: 不建立 Security Group 對外完全開放的 EC2
6. **No Public RDS/EMR**: 不使用公開存取的 RDS 或 EMR
7. **No Sensitive Data**: 不上傳個人資料、財務資訊等敏感資料集至 AWS
8. **No Credentials in Git**: .env 和 credentials 必須在 .gitignore
9. **Keep .kiro/**: .kiro 資料夾不可加入 .gitignore，必須上傳至 GitHub
10. **Resource Efficiency**: 僅啟動必要的執行個體，避免浪費

## Bedrock 使用注意
- 每次呼叫前必須執行 `BedrockRateLimiter.wait()`
- 開發完成後撤銷不再使用的模型存取權
- 不進行大規模模型訓練

## 部署 Checklist
- [ ] 確認所有 Stack 部署在 us-east-1
- [ ] 確認 S3 Block Public Access 啟用
- [ ] 確認 Fargate 在 Private Subnet
- [ ] 確認 .env 在 .gitignore
- [ ] 確認 .kiro/ 不在 .gitignore
- [ ] 確認 Bedrock RPS ≤ 1
