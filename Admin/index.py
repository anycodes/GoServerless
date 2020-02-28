# -*- coding: utf8 -*-
import os
import re
import json
import time
import random
import base64
import hashlib
import xmltodict
import urllib.parse
import urllib.request
from urllib3 import encode_multipart_formdata
from qcloud_cos_v5 import CosConfig
from qcloud_cos_v5 import CosS3Client
from tencentcloud.common import credential
from tbp import tbp_client, models as tbp_models
from tts import tts_client, models as tts_models
from tencentcloud.scf.v20180416 import scf_client, models as scf_models

bot_id = os.environ.get('bot_id')
bucket = os.environ.get('bucket')
secret_id = os.environ.get('secret_id')
secret_key = os.environ.get('secret_key')
region = os.environ.get('region')
wxtoken = os.environ.get('wxtoken')
appid = os.environ.get('appid')
secret = os.environ.get('secret')
cosClient = CosS3Client(CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key))
scfClient = scf_client.ScfClient(credential.Credential(secret_id, secret_key), region)
tbpClient = tbp_client.TbpClient(credential.Credential(secret_id, secret_key), region)
ttsClient = tts_client.TtsClient(credential.Credential(secret_id, secret_key), region)

key = 'news/content.json'
indexKey = 'news/content_index.json'
accessTokenKey = 'access/token.json'
accessToken = None
articlesList = None


def getAccessToken():
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Basic_Information/Get_access_token.html
    正常返回：{"access_token":"ACCESS_TOKEN","expires_in":7200}
    异常返回：{"errcode":40013,"errmsg":"invalid appid"}
    :return:
    '''
    global accessToken

    # 第一次判断是判断本地是否已经有了accessToken，考虑到容器复用情况
    if accessToken:
        if int(time.time()) - int(accessToken["time"]) <= 7000:
            return accessToken["access_token"]

    # 如果本地没有accessToken，可以去cos获取
    try:
        response = cosClient.get_object(
            Bucket=bucket,
            Key=accessTokenKey,
        )
        response['Body'].get_stream_to_file('/tmp/token.json')
        with open('/tmp/token.json') as f:
            accessToken = json.loads(f.read())
    except:
        pass

    # 这一次是看cos中是否有，如果cos中有的话，再次进行判断段
    if accessToken:
        if int(time.time()) - int(accessToken["time"]) <= 7000:
            return accessToken["access_token"]

    # 如果此时流程还没停止，则说明accessToken还没获得到，就需要从接口获得，并且同步给cos
    url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=%s&secret=%s" % (appid, secret)
    accessTokenResult = json.loads(urllib.request.urlopen(url).read().decode("utf-8"))
    accessToken = {"time": int(time.time()), "access_token": accessTokenResult["access_token"]}
    print(accessToken)
    response = cosClient.put_object(
        Bucket=bucket,
        Body=json.dumps(accessToken).encode("utf-8"),
        Key=accessTokenKey,
        EnableMD5=False
    )
    return None if "errcode" in accessToken else accessToken["access_token"]


def checkSignature(param):
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Basic_Information/Access_Overview.html
    :param param:
    :return:
    '''
    signature = param['signature']
    timestamp = param['timestamp']
    nonce = param["nonce"]
    tmparr = [wxtoken, timestamp, nonce]
    tmparr.sort()
    tmpstr = ''.join(tmparr)
    tmpstr = hashlib.sha1(tmpstr.encode("utf-8")).hexdigest()
    return tmpstr == signature


def response(body, status=200):
    return {
        "isBase64Encoded": False,
        "statusCode": status,
        "headers": {"Content-Type": "text/html"},
        "body": body
    }


def setMenu(menu):
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Custom_Menus/Creating_Custom-Defined_Menu.html
    正确返回：{"errcode":0,"errmsg":"ok"}
    异常返回：{"errcode":40018,"errmsg":"invalid button name size"}
    :return:
    '''
    accessToken = getAccessToken()
    if not accessToken:
        return "Get Access Token Error"

    url = "https://api.weixin.qq.com/cgi-bin/menu/create?access_token=%s" % accessToken
    postData = urllib.parse.urlencode(menu).encode("utf-8")
    requestAttr = urllib.request.Request(url=url, data=postData)
    responseAttr = urllib.request.urlopen(requestAttr)
    responseData = json.loads(responseAttr.read())
    return responseData['errmsg'] if "errcode" in responseData else "success"


def getTheTotalOfAllMaterials():
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Get_the_total_of_all_materials.html
    :return:
    '''
    accessToken = getAccessToken()
    if not accessToken:
        return "Get Access Token Error"
    url = "https://api.weixin.qq.com/cgi-bin/material/get_materialcount?access_token=%s" % accessToken
    responseAttr = urllib.request.urlopen(url=url)
    return json.loads(responseAttr.read())


def getMaterialsList(listType, count):
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Get_materials_list.html
    :return:
    '''
    accessToken = getAccessToken()
    if not accessToken:
        return "Get Access Token Error"

    url = "https://api.weixin.qq.com/cgi-bin/material/batchget_material?access_token=%s" % accessToken
    materialsList = []
    for i in range(1, int(count / 20) + 2):
        requestAttr = urllib.request.Request(url=url, data=json.dumps({
            "type": listType,
            "offset": 20 * (i - 1),
            "count": 20
        }).encode("utf-8"), headers={
            "Content-Type": "application/json"
        })
        responseAttr = urllib.request.urlopen(requestAttr)
        responseData = json.loads(responseAttr.read().decode("utf-8"))
        materialsList = materialsList + responseData["item"]
    return materialsList


def saveNewsToCos():
    global articlesList
    articlesList = getMaterialsList("news", getTheTotalOfAllMaterials()['news_count'])
    try:
        cosClient.put_object(
            Bucket=bucket,
            Body=json.dumps(articlesList).encode("utf-8"),
            Key=key,
            EnableMD5=False
        )
        req = scf_models.InvokeRequest()
        params = '{"FunctionName":"Weixin_GoServerless_GetIndexFile", "ClientContext":"{\\"key\\": \\"%s\\", \\"index_key\\": \\"%s\\"}"}' % (
            key, indexKey)
        req.from_json_string(params)
        resp = scfClient.Invoke(req)
        resp.to_json_string()
        response = cosClient.get_object(
            Bucket=bucket,
            Key=key,
        )
        response['Body'].get_stream_to_file('/tmp/content.json')
        with open('/tmp/content.json') as f:
            articlesList = json.loads(f.read())
        return True
    except Exception as e:
        print(e)
        return False


def getEvent(event):
    '''
    对Event进行解析
    :param event:
    :return:
    '''
    return xmltodict.parse(event["body"])["xml"]


def textXML(body, event):
    '''
    :param body: {"msg": "test"}
        msg: 必填，回复的消息内容（换行：在content中能够换行，微信客户端就支持换行显示）
    :param event:
    :return:
    '''
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[text]]></MsgType>
              <Content><![CDATA[{msg}]]></Content></xml>""".format(toUser=event["FromUserName"],
                                                                   fromUser=event["ToUserName"],
                                                                   time=int(time.time()),
                                                                   msg=body["msg"])


def pictureXML(body, event):
    '''
    :param body:  {"media_id": 123}
        media_id: 必填，通过素材管理中的接口上传多媒体文件，得到的id。
    :param event:
    :return:
    '''
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[image]]></MsgType>
              <Image>
                <MediaId><![CDATA[{media_id}]]></MediaId>
              </Image></xml>""".format(toUser=event["FromUserName"],
                                       fromUser=event["ToUserName"],
                                       time=int(time.time()),
                                       media_id=body["media_id"])


def voiceXML(body, event):
    '''
    :param body: {"media_id": 123}
        media_id: 必填，通过素材管理中的接口上传多媒体文件，得到的id
    :param event:
    :return:
    '''
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[voice]]></MsgType>
              <Voice>
                <MediaId><![CDATA[{media_id}]]></MediaId>
              </Voice></xml>""".format(toUser=event["FromUserName"],
                                       fromUser=event["ToUserName"],
                                       time=int(time.time()),
                                       media_id=body["media_id"])


def videoXML(body, event):
    '''
    :param body: {"media_id": 123, "title": "test", "description": "test}
        media_id: 必填，通过素材管理中的接口上传多媒体文件，得到的id
        title:：选填，视频消息的标题
        description：选填，视频消息的描述
    :param event:
    :return:
    '''
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[video]]></MsgType>
              <Video>
                <MediaId><![CDATA[{media_id}]]></MediaId>
                <Title><![CDATA[{title}]]></Title>
                <Description><![CDATA[{description}]]></Description>
              </Video></xml>""".format(toUser=event["FromUserName"],
                                       fromUser=event["ToUserName"],
                                       time=int(time.time()),
                                       media_id=body["media_id"],
                                       title=body.get('title', ''),
                                       description=body.get('description', ''))


def musicXML(body, event):
    '''
    :param body:  {"media_id": 123, "title": "test", "description": "test}
        media_id：必填，缩略图的媒体id，通过素材管理中的接口上传多媒体文件，得到的id
        title：选填，音乐标题
        description：选填，音乐描述
        url：选填，音乐链接
        hq_url：选填，高质量音乐链接，WIFI环境优先使用该链接播放音乐
    :param event:
    :return:
    '''
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[music]]></MsgType>
              <Music>
                <Title><![CDATA[{title}]]></Title>
                <Description><![CDATA[{description}]]></Description>
                <MusicUrl><![CDATA[{url}]]></MusicUrl>
                <HQMusicUrl><![CDATA[{hq_url}]]></HQMusicUrl>
                <ThumbMediaId><![CDATA[{media_id}]]></ThumbMediaId>
              </Music></xml>""".format(toUser=event["FromUserName"],
                                       fromUser=event["ToUserName"],
                                       time=int(time.time()),
                                       media_id=body["media_id"],
                                       title=body.get('title', ''),
                                       url=body.get('url', ''),
                                       hq_url=body.get('hq_url', ''),
                                       description=body.get('description', ''))


def articlesXML(body, event):
    '''
    :param body: 一个list [{"title":"test", "description": "test", "picUrl": "test", "url": "test"}]
        title：必填，图文消息标题
        description：必填，图文消息描述
        picUrl：必填，图片链接，支持JPG、PNG格式，较好的效果为大图360*200，小图200*200
        url：必填，点击图文消息跳转链接
    :param event:
    :return:
    '''
    if len(body["articles"]) > 8:  # 最多只允许返回8个
        body["articles"] = body["articles"][0:8]
    tempArticle = """<item>
      <Title><![CDATA[{title}]]></Title>
      <Description><![CDATA[{description}]]></Description>
      <PicUrl><![CDATA[{picurl}]]></PicUrl>
      <Url><![CDATA[{url}]]></Url>
    </item>"""
    return """<xml><ToUserName><![CDATA[{toUser}]]></ToUserName>
              <FromUserName><![CDATA[{fromUser}]]></FromUserName>
              <CreateTime>{time}</CreateTime>
              <MsgType><![CDATA[news]]></MsgType>
              <ArticleCount>{count}</ArticleCount>
              <Articles>
                {articles}
              </Articles></xml>""".format(toUser=event["FromUserName"],
                                          fromUser=event["ToUserName"],
                                          time=int(time.time()),
                                          count=len(body["articles"]),
                                          articles="".join([tempArticle.format(
                                              title=eveArticle['title'],
                                              description=eveArticle['description'],
                                              picurl=eveArticle['picurl'],
                                              url=eveArticle['url']
                                          ) for eveArticle in body["articles"]]))


def searchNews(sentence):
    req = scf_models.InvokeRequest()
    params = '{"FunctionName":"Weixin_GoServerless_SearchNews", "ClientContext":"{\\"sentence\\": \\"%s\\", \\"key\\": \\"%s\\"}"}' % (
        sentence, indexKey)
    req.from_json_string(params)
    resp = scfClient.Invoke(req)
    print(json.loads(json.loads(resp.to_json_string())['Result']["RetMsg"]))
    media_id = json.loads(json.loads(json.loads(resp.to_json_string())['Result']["RetMsg"])["result"])
    return media_id if media_id else None


def getNewsInfo(news):
    global articlesList
    if not articlesList:
        try:
            response = cosClient.get_object(
                Bucket=bucket,
                Key=key,
            )
            response['Body'].get_stream_to_file('/tmp/content.json')
            with open('/tmp/content.json') as f:
                articlesList = json.loads(f.read())
        except:
            pass

    for eve in articlesList:
        print(eve)

    articles = []
    if articlesList:
        for eve in news:
            if eve in articlesList:
                articles.append({
                    "title": articlesList[eve]["title"],
                    "description": articlesList[eve]["digest"],
                    "picurl": articlesList[eve]["thumb_url"],
                    "url": articlesList[eve]["url"],
                })
    return articles


def chatBot(user, content):
    '''
    开发文档：https://cloud.tencent.com/document/product/1060/37438
    :param user: 用户id
    :param content: 聊天内容
    :return: 返回机器人说的话，如果出现故障返回None
    '''
    try:
        req = tbp_models.TextProcessRequest()
        params = '{"BotId":"%s","BotEnv":"release","TerminalId":"%s","InputText":"%s"}' % (
            bot_id, user, content
        )
        req.from_json_string(params)
        resp = tbpClient.TextProcess(req)
        return json.loads(resp.to_json_string())['ResponseMessage']['GroupList'][0]['Content']
    except Exception as e:
        print(e)
        return None


def getNewsResult(media_id, event):
    if media_id:
        news = getNewsInfo(media_id)
        if len(news) == 1:
            return articlesXML({"articles": news}, event)
        if len(news) > 1:
            content = "\n".join(['<a href="%s">/:li %s</a>' % (eve["url"], eve["title"]) for eve in news])
            return textXML({"msg": "为您搜索到以下相关内容：\n" + content}, event)
    return None


def text2Voice(text):
    '''
    文档地址：https://cloud.tencent.com/document/product/1073/37995
    :param text: 带转换的文本
    :return: 返回转换后的文件地址
    '''
    try:
        req = tts_models.TextToVoiceRequest()
        params = '{"Text":"%s","SessionId":"%s","ModelType":1,"VoiceType":1002}' % (
            text, "".join(random.sample('zyxwvutsrqponmlkjihgfedcba', 7)))
        req.from_json_string(params)
        resp = ttsClient.TextToVoice(req)
        file = '/tmp/' + "".join(random.sample('zyxwvutsrqponmlkjihgfedcba', 7)) + ".wav"
        with open(file, 'wb') as f:
            f.write(base64.b64decode(json.loads(resp.to_json_string())["Audio"]))
        return file

    except Exception as e:
        print(e)
        return None


def addingOtherPermanentAssets(file, fileType):
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Adding_Permanent_Assets.html
    返回结果：{
                "media_id":"HQOG98Gpaa4KcvU1L0MPEcyy31LSuHhRi8gD3pvebhI",
                "url":"http:\/\/mmbiz.qpic.cn\/sz_mmbiz_png\/icxY5TTGTBibSyZPfLAEZmeaicUczsoGUpqLgBlRbNxeic4R8r94j60BiaxDLEZTAK7I7qubG3Ik808P8jYLdFJTcOA\/0?wx_fmt=png",
                "item":[]
            }
    :param file:
    :return:
    '''
    typeDict = {
        "voice": "wav"
    }
    url = "https://api.weixin.qq.com/cgi-bin/material/add_material?access_token=%s&type=%s" % (
        getAccessToken(), fileType)
    boundary = '----WebKitFormBoundary7MA4YWxk%s' % "".join(random.sample('zyxwvutsrqponmlkjihgfedcba', 7))
    with open(file, 'rb') as f:
        fileData = f.read()
    data = {'media': (os.path.split(file)[1], fileData, typeDict[fileType])}
    headers = {
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "User-Agent": "okhttp/3.10.0"
    }
    reqAttr = urllib.request.Request(url=url,
                                     data=encode_multipart_formdata(data, boundary=boundary)[0],
                                     headers=headers)
    responseData = json.loads(urllib.request.urlopen(reqAttr).read().decode("utf-8"))

    try:
        for eveVoice in getMaterialsList("voice", getTheTotalOfAllMaterials()['voice_count']):
            try:
                if int(time.time()) - int(eveVoice["update_time"]) > 60:
                    deletingPermanentAssets(eveVoice['media_id'])
            except:
                pass
    except:
        pass

    return responseData['media_id'] if "media_id" in responseData else None


def getMaterial(media_id):
    url = 'https://api.weixin.qq.com/cgi-bin/material/get_material?access_token=%s' % (getAccessToken())
    data = {
        "media_id": media_id
    }
    postData = json.dumps(data).encode("utf-8")
    reqAttr = urllib.request.Request(url=url, data=postData)
    print(urllib.request.urlopen(reqAttr).read())


def deletingPermanentAssets(media_id):
    '''
    文档地址：https://developers.weixin.qq.com/doc/offiaccount/Asset_Management/Deleting_Permanent_Assets.html
    :return:
    '''
    url = 'https://api.weixin.qq.com/cgi-bin/material/del_material?access_token=%s' % (getAccessToken())
    data = {
        "media_id": media_id
    }
    postData = json.dumps(data).encode("utf-8")
    reqAttr = urllib.request.Request(url=url, data=postData)
    print(urllib.request.urlopen(reqAttr).read())


def main_handler(event, context):
    print('event: ', event)

    if event["path"] == '/setMenu':  # 设置菜单接口
        menu = {
            "button": [
                {
                    "type": "view",
                    "name": "精彩文章",
                    "url": "https://mp.weixin.qq.com/mp/homepage?__biz=Mzg2NzE4MDExNw==&hid=2&sn=168bd0620ee79cd35d0a80cddb9f2487"
                },
                {
                    "type": "view",
                    "name": "开源项目",
                    "url": "https://mp.weixin.qq.com/mp/homepage?__biz=Mzg2NzE4MDExNw==&hid=1&sn=69444401c5ed9746aeb1384fa6a9a201"
                },
                {
                    "type": "miniprogram",
                    "name": "在线编程",
                    "appid": "wx453cb539f9f963b2",
                    "pagepath": "/page/index"
                }]
        }
        return response(setMenu(menu))

    if event["path"] == '/setIndex':
        return response("success" if saveNewsToCos() else "failed")

    if 'echostr' in event['queryString']:  # 接入时的校验
        return response(event['queryString']['echostr'] if checkSignature(event['queryString']) else False)
    else:  # 用户消息/事件
        event = getEvent(event)
        if event["MsgType"] == "text":
            # 文本消息
            media_id = searchNews(event["Content"])
            result = getNewsResult(media_id, event)
            if not result:
                chatBotResponse = chatBot(event["FromUserName"], event["Content"])
                result = textXML({"msg": chatBotResponse if chatBotResponse else "目前还没有类似的文章被发布在这个公众号上"}, event)
            return response(body=result)
        elif event["MsgType"] == "image":
            # 图片消息
            return response(body=textXML({"msg": "这是一个图片消息"}, event))
        elif event["MsgType"] == "voice":
            # 语音消息
            media_id = searchNews(event["Recognition"])
            result = getNewsResult(media_id, event)
            if not result:
                chatBotResponse = chatBot(event["FromUserName"], event["Recognition"])
                if chatBotResponse:
                    voiceFile = text2Voice(chatBotResponse)
                    if voiceFile:
                        uploadResult = addingOtherPermanentAssets(voiceFile, 'voice')
                        if uploadResult:
                            result = voiceXML({"media_id": uploadResult}, event)
            if not result:
                result = textXML({"msg": "目前还没有类似的文章被发布在这个公众号上"}, event)
            return response(body=result)
        elif event["MsgType"] == "video":
            # 视频消息
            pass
        elif event["MsgType"] == "shortvideo":
            # 小视频消息
            pass
        elif event["MsgType"] == "location":
            # 地理位置消息
            pass
        elif event["MsgType"] == "link":
            # 链接消息
            pass
        elif event["MsgType"] == "event":
            # 事件消息
            if event["Event"] == "subscribe":
                # 订阅事件
                if event.get('EventKey', None):
                    # 用户未关注时，进行关注后的事件推送（带参数的二维码）
                    pass
                else:
                    content = "😘 欢迎您关注GoServerless，让我们一起玩转Serverless吧！\n" \
                              "😄 初来乍到，让我来介绍一下吧：\n" \
                              "🔥 <a href='https://mp.weixin.qq.com/mp/homepage?__biz=Mzg2NzE4MDExNw==&hid=2&sn=168bd0620ee79cd35d0a80cddb9f2487'>精彩文章</a>\n" \
                              "🔥 <a href='https://mp.weixin.qq.com/mp/homepage?__biz=Mzg2NzE4MDExNw==&hid=1&sn=69444401c5ed9746aeb1384fa6a9a201'>开源项目</a>\n" \
                              "🔥 <a href='https://mp.weixin.qq.com/mp/homepage?__biz=Mzg2NzE4MDExNw==&hid=3&sn=a98b28c92399068cca596ae620c73374'>视频中心</a>\n" \
                              "🔥 <a href='https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=Mzg2NzE4MDExNw==&scene=124#wechat_redirect'>历史文章</a>\n" \
                              "🎃 如果你有问题可以直接提问，系统会自动给您搜索，例如您问：Serverless架构下如何上传图片？"

                    return response(textXML({"msg": content}, event))
            elif event["Event"] == "unsubscribe":
                # 取消订阅事件
                pass
            elif event["Event"] == "SCAN":
                # 用户已关注时的事件推送（带参数的二维码）
                pass
            elif event["Event"] == "LOCATION":
                # 上报地理位置事件
                pass
            elif event["Event"] == "CLICK":
                # 点击菜单拉取消息时的事件推送
                pass
            elif event["Event"] == "VIEW":
                # 点击菜单跳转链接时的事件推送
                pass
