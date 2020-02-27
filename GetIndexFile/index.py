# -*- coding: utf8 -*-
import os
import re
import json
import random
from snownlp import SnowNLP
from qcloud_cos_v5 import CosConfig
from qcloud_cos_v5 import CosS3Client

bucket = os.environ.get('bucket')
secret_id = os.environ.get('secret_id')
secret_key = os.environ.get('secret_key')
region = os.environ.get('region')
client = CosS3Client(CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key))


def main_handler(event, context):
    response = client.get_object(
        Bucket=bucket,
        Key=event["key"],
    )
    response['Body'].get_stream_to_file('/tmp/output.txt')

    with open('/tmp/output.txt') as f:
        data = json.loads(f.read())

    articlesIndex = []
    articles = {}
    tempContentList = [
        "_", "&nbsp;",
        "点击Go Serverless关注我们这是一个全新的微信公众号，大家的支持是我分享的动力，如果您觉得这个公众号还可以，欢迎转发朋友圈，或者转发给好友，感谢支持。",
        "点击GoServerless关注我们感谢各位小伙伴的关注和阅读，这是一个全新的公众号，非常希望您可以把这个公众号分享给您的小伙伴，更多人的关注是我更新的动力，我会在这里更新超级多Serverless架构的经验，分享更多有趣的小项目。",
    ]
    for eveItem in data:
        for i in range(0, len(eveItem['content']['news_item'])):
            content = eveItem['content']['news_item'][i]['content']
            content = re.sub(r'<code(.*?)</code>', '_', content)
            content = re.sub(r'<.*?>', '', content)
            for eve in tempContentList:
                content = content.replace(eve, "")
            if "Serverless实践列表" in content:
                content = content.split("Serverless实践列表")[i]
            desc = "%s。%s。%s" % (
                eveItem['content']['news_item'][i]['title'],
                eveItem['content']['news_item'][i]['digest'],
                "。".join(SnowNLP(content).summary(1))
            )
            tempKey = "".join(random.sample('zyxwvutsrqponmlkjihgfedcba', 5))
            articlesIndex.append(
                {
                    "media_id": tempKey,
                    "description": desc
                }
            )
            articles[tempKey] = eveItem['content']['news_item'][i]

    client.put_object(
        Bucket=bucket,
        Body=json.dumps(articlesIndex).encode("utf-8"),
        Key=event['index_key'],
        EnableMD5=False
    )
    client.put_object(
        Bucket=bucket,
        Body=json.dumps(articles).encode("utf-8"),
        Key=event['key'],
        EnableMD5=False
    )
