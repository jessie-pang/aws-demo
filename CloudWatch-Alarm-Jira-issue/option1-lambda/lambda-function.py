import json
import os
import requests

JIRA_DOMAIN = os.environ['JIRA_DOMAIN'] 
JIRA_USER = os.environ['JIRA_USER']
JIRA_API_TOKEN = os.environ['JIRA_API_TOKEN']

PROJECT_KEY = os.environ['PROJECT_KEY'] 
ISSUE_TYPE = os.environ['ISSUE_TYPE']

def lambda_handler(event, context):

  message = json.loads(event['Records'][0]['Sns']['Message'])
  
  alarm_name = message['AlarmName']
  metric_name = message['Trigger']['MetricName']
  reason = message['NewStateReason']


  issue = {
        "fields": {
          "project": {"key": PROJECT_KEY},
          "issuetype": {"id": ISSUE_TYPE},  
          "summary": f"From Lambda: {alarm_name} Alarm Triggered",
          "description": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": f"The alarm {alarm_name} was triggered due to metric {metric_name} exceeding the threshold.\nReason: {reason}"
                        }
                    ]
                }
            ]
        }
        }
  }
  print(issue)
    
  url = f"https://{JIRA_DOMAIN}.atlassian.net/rest/api/3/issue/"
  print(url)

  headers = {"Content-Type": "application/json"}
  auth = (JIRA_USER, JIRA_API_TOKEN)

  response = requests.post(url, json=issue, headers=headers, auth=auth)
  print(response.status_code)

  if response.status_code == 201:
    print("Jira ticket created successfully!")
  else:
    print(f"Error creating Jira ticket: {response.text}")

  return {
    'statusCode': 200
  }
