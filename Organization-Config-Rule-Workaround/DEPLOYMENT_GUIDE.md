# 完整自动化部署指南

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      管理账户 (Hub)                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐      ┌──────────────────┐           │
│  │ CloudFormation   │      │  Lambda Function │           │
│  │   StackSets      │◄─────┤  (Custom Rules)  │           │
│  └────────┬─────────┘      └──────────────────┘           │
│           │                                                 │
│           │ 部署                                            │
│           ▼                                                 │
│  ┌──────────────────┐      ┌──────────────────┐           │
│  │  EventBridge     │      │  Lambda Function │           │
│  │  (监听新账户)     │─────►│  (自动部署)       │           │
│  └──────────────────┘      └──────────────────┘           │
│                                                             │
│  ┌──────────────────┐                                      │
│  │  SCP 策略        │                                      │
│  │  (保护规则)       │                                      │
│  └──────────────────┘                                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ 自动部署
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    成员账户 (Spoke)                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐      ┌──────────────────┐           │
│  │  Config Rules    │      │  Config Recorder │           │
│  │  (4条规则)        │      │  (持续记录)       │           │
│  └──────────────────┘      └──────────────────┘           │
│                                                             │
│  ✗ 无法修改或删除规则 (SCP 保护)                             │
└─────────────────────────────────────────────────────────────┘
```

## 部署步骤

### 阶段 1: 基础设施准备

#### 1.1 在管理账户创建 StackSet 管理角色

```bash
aws iam create-role \
  --role-name AWSCloudFormationStackSetAdministrationRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "cloudformation.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy \
  --role-name AWSCloudFormationStackSetAdministrationRole \
  --policy-name AssumeRole-AWSCloudFormationStackSetExecutionRole \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws-cn:iam::*:role/AWSCloudFormationStackSetExecutionRole"
    }]
  }'
```

#### 1.2 在所有成员账户创建执行角色

```bash
# 在每个成员账户执行
MANAGEMENT_ACCOUNT_ID="7014XXXX6525"

aws iam create-role \
  --role-name AWSCloudFormationStackSetExecutionRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws-cn:iam::'$MANAGEMENT_ACCOUNT_ID':root"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy \
  --role-name AWSCloudFormationStackSetExecutionRole \
  --policy-name ConfigRulesStackSetPolicy \
  --policy-document file:///tmp/stackset-test/stackset-execution-role-policy.json
```

### 阶段 2: 部署 Config Rules

#### 2.1 创建 Custom Rule Lambda 函数

```bash
# 部署 Lambda
cd /tmp/stackset-test
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name OrgConfigRuleFunction \
  --runtime python3.9 \
  --role arn:aws-cn:iam::7014XXXX6525:role/ConfigRuleLambdaRole \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --region cn-northwest-1
```

#### 2.2 创建 StackSet

```bash
aws cloudformation create-stack-set \
  --stack-set-name org-config-rules \
  --template-body file://config-rules-template.yaml \
  --parameters ParameterKey=CentralLambdaArn,ParameterValue=arn:aws-cn:lambda:cn-northwest-1:7014XXXX6525:function:OrgConfigRuleFunction \
  --capabilities CAPABILITY_NAMED_IAM \
  --administration-role-arn arn:aws-cn:iam::7014XXXX6525:role/AWSCloudFormationStackSetAdministrationRole \
  --execution-role-name AWSCloudFormationStackSetExecutionRole \
  --region cn-northwest-1
```

#### 2.3 部署到现有账户

```bash
aws cloudformation create-stack-instances \
  --stack-set-name org-config-rules \
  --accounts 111111111111 222222222222 333333333333 \
  --regions cn-northwest-1 \
  --region cn-northwest-1
```

### 阶段 3: 配置自动化

#### 3.1 创建自动部署 Lambda 函数

```bash
# 创建 Lambda 执行角色
aws iam create-role \
  --role-name AutoDeployConfigRulesRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# 附加权限
aws iam put-role-policy \
  --role-name AutoDeployConfigRulesRole \
  --policy-name AutoDeployPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "cloudformation:CreateStackInstances",
          "cloudformation:DescribeStackSet"
        ],
        "Resource": "arn:aws-cn:cloudformation:*:*:stackset/org-config-rules:*"
      },
      {
        "Effect": "Allow",
        "Action": ["organizations:DescribeAccount"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": "*"
      }
    ]
  }'

# 部署 Lambda
cd /tmp/stackset-test
zip auto-deploy.zip auto-add-account-lambda.py

aws lambda create-function \
  --function-name AutoDeployConfigRules \
  --runtime python3.9 \
  --role arn:aws-cn:iam::7014XXXX6525:role/AutoDeployConfigRulesRole \
  --handler auto-add-account-lambda.lambda_handler \
  --zip-file fileb://auto-deploy.zip \
  --environment Variables={STACKSET_NAME=org-config-rules,REGIONS=cn-northwest-1} \
  --region cn-northwest-1
```

#### 3.2 创建 EventBridge 规则

```bash
# 创建规则
aws events put-rule \
  --name auto-deploy-config-rules \
  --description "Auto deploy Config Rules to new accounts" \
  --event-pattern '{
    "source": ["aws.organizations"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
      "eventName": ["CreateAccountResult"]
    }
  }' \
  --region cn-northwest-1

# 添加 Lambda 目标
aws events put-targets \
  --rule auto-deploy-config-rules \
  --targets "Id"="1","Arn"="arn:aws-cn:lambda:cn-northwest-1:7014XXXX6525:function:AutoDeployConfigRules" \
  --region cn-northwest-1

# 授予 EventBridge 调用 Lambda 的权限
aws lambda add-permission \
  --function-name AutoDeployConfigRules \
  --statement-id AllowEventBridgeInvoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws-cn:events:cn-northwest-1:7014XXXX6525:rule/auto-deploy-config-rules \
  --region cn-northwest-1
```

### 阶段 4: 部署 SCP 保护

#### 4.1 创建 SCP 策略

```bash
# 替换 ${ManagementAccountId} 为实际的管理账户 ID
sed 's/${ManagementAccountId}/7014XXXX6525/g' /tmp/stackset-test/scp-deny-config-modification.json > /tmp/scp-final.json

# 创建策略
POLICY_ID=$(aws organizations create-policy \
  --name DenyConfigRuleModification \
  --description "Prevent member accounts from modifying organization Config Rules" \
  --content file:///tmp/scp-final.json \
  --type SERVICE_CONTROL_POLICY \
  --query 'Policy.PolicySummary.Id' \
  --output text)

echo "SCP Policy ID: $POLICY_ID"
```

#### 4.2 附加 SCP 到 OU 或账户

```bash
# 附加到根 OU（影响所有账户）
ROOT_ID=$(aws organizations list-roots --query 'Roots[0].Id' --output text)
aws organizations attach-policy \
  --policy-id $POLICY_ID \
  --target-id $ROOT_ID

# 或附加到特定 OU
aws organizations attach-policy \
  --policy-id $POLICY_ID \
  --target-id ou-xxxx-xxxxxxxx

# 或附加到特定账户
aws organizations attach-policy \
  --policy-id $POLICY_ID \
  --target-id 123456789012
```

## 验证部署

### 验证 StackSet 部署

```bash
aws cloudformation list-stack-instances \
  --stack-set-name org-config-rules \
  --region cn-northwest-1
```

### 验证 Config Rules

```bash
# 在任意成员账户
aws configservice describe-config-rules \
  --region cn-northwest-1 \
  --query 'ConfigRules[?starts_with(ConfigRuleName, `test-org`)].ConfigRuleName'
```

### 验证 SCP 保护

```bash
# 在成员账户尝试删除规则（应该失败）
aws configservice delete-config-rule \
  --config-rule-name test-org-s3-encryption \
  --region cn-northwest-1

# 预期错误: AccessDeniedException
```

### 验证自动部署

```bash
# 创建新账户后，检查 Lambda 日志
aws logs tail /aws/lambda/AutoDeployConfigRules --follow --region cn-northwest-1

# 检查新账户的 StackSet 实例
aws cloudformation list-stack-instances \
  --stack-set-name org-config-rules \
  --region cn-northwest-1
```

## 日常运维

### 更新规则

```bash
# 修改模板后更新
aws cloudformation update-stack-set \
  --stack-set-name org-config-rules \
  --template-body file://config-rules-template-v2.yaml \
  --region cn-northwest-1
```

### 添加新区域

```bash
aws cloudformation create-stack-instances \
  --stack-set-name org-config-rules \
  --accounts 111111111111 222222222222 \
  --regions cn-north-1 \
  --region cn-northwest-1
```

### 查看规则定义

```bash
aws cloudformation get-template \
  --stack-set-name org-config-rules \
  --region cn-northwest-1 \
  --query 'TemplateBody' \
  --output text | yq eval '.Resources | to_entries | .[] | select(.value.Type == "AWS::Config::ConfigRule")'
```

## 故障排查

### StackSet 部署失败

```bash
# 查看操作详情
aws cloudformation describe-stack-set-operation \
  --stack-set-name org-config-rules \
  --operation-id <operation-id> \
  --region cn-northwest-1

# 查看特定账户的失败原因
aws cloudformation describe-stack-instance \
  --stack-set-name org-config-rules \
  --stack-instance-account <account-id> \
  --stack-instance-region cn-northwest-1 \
  --region cn-northwest-1
```

### Lambda 自动部署失败

```bash
# 查看 Lambda 日志
aws logs tail /aws/lambda/AutoDeployConfigRules --since 1h --region cn-northwest-1

# 检查 Lambda 权限
aws lambda get-policy \
  --function-name AutoDeployConfigRules \
  --region cn-northwest-1
```

### SCP 问题

```bash
# 列出附加的策略
aws organizations list-policies-for-target \
  --target-id <account-or-ou-id> \
  --filter SERVICE_CONTROL_POLICY

# 查看策略内容
aws organizations describe-policy \
  --policy-id <policy-id>
```

