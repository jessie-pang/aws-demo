import boto3
import os

cfn = boto3.client('cloudformation')
orgs = boto3.client('organizations')

STACKSET_NAME = os.environ['STACKSET_NAME']
REGIONS = os.environ.get('REGIONS', 'cn-northwest-1').split(',')

def lambda_handler(event, context):
    """
    监听 Organizations 账户创建事件，自动为新账户部署 Config Rules
    
    EventBridge 事件源: aws.organizations
    事件类型: CreateAccountResult
    """
    
    print(f"收到事件: {event}")
    
    # 检查是否是账户创建成功事件
    if event['detail']['eventName'] != 'CreateAccountResult':
        print("非账户创建事件，跳过")
        return
    
    service_event_details = event['detail']['serviceEventDetails']
    create_account_status = service_event_details.get('createAccountStatus', {})
    
    # 检查账户创建状态
    if create_account_status.get('state') != 'SUCCEEDED':
        print(f"账户创建未成功，状态: {create_account_status.get('state')}")
        return
    
    new_account_id = create_account_status.get('accountId')
    account_name = create_account_status.get('accountName')
    
    if not new_account_id:
        print("无法获取新账户 ID")
        return
    
    print(f"检测到新账户: {account_name} ({new_account_id})")
    
    try:
        # 为新账户创建 StackSet 实例
        response = cfn.create_stack_instances(
            StackSetName=STACKSET_NAME,
            Accounts=[new_account_id],
            Regions=REGIONS,
            OperationPreferences={
                'MaxConcurrentCount': 1,
                'FailureToleranceCount': 0
            }
        )
        
        operation_id = response['OperationId']
        print(f"已为账户 {new_account_id} 创建 StackSet 实例")
        print(f"操作 ID: {operation_id}")
        
        # 可选: 发送通知
        # sns.publish(...)
        
        return {
            'statusCode': 200,
            'body': {
                'message': f'Successfully deployed Config Rules to account {new_account_id}',
                'accountId': new_account_id,
                'accountName': account_name,
                'operationId': operation_id
            }
        }
        
    except Exception as e:
        print(f"部署失败: {str(e)}")
        # 可选: 发送告警
        # sns.publish(...)
        raise
