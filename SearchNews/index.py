import os
import json
import jieba
from qcloud_cos_v5 import CosConfig
from qcloud_cos_v5 import CosS3Client
from collections import defaultdict
from gensim import corpora, models, similarities

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

    articles = []
    articlesDict = {}
    for eve in data:
        print(eve)
        articles.append(eve['description'])
        articlesDict[eve['description']] = eve['media_id']

    sentence = event["sentence"]

    documents = []
    for eve_sentence in articles:
        tempData = " ".join(jieba.cut(eve_sentence))
        documents.append(tempData)
    texts = [[word for word in document.split()] for document in documents]
    frequency = defaultdict(int)
    for text in texts:
        for word in text:
            frequency[word] += 1
    dictionary = corpora.Dictionary(texts)
    new_xs = dictionary.doc2bow(jieba.cut(sentence))
    corpus = [dictionary.doc2bow(text) for text in texts]
    tfidf = models.TfidfModel(corpus)
    featurenum = len(dictionary.token2id.keys())
    sim = similarities.SparseMatrixSimilarity(
        tfidf[corpus],
        num_features=featurenum
    )[tfidf[new_xs]]
    answer_list = [(sim[i], articles[i]) for i in range(0, len(articles))]
    answer_list.sort(key=lambda x: x[0], reverse=True)
    result = []
    print(len(answer_list), answer_list)
    for eve in answer_list:
        if eve[0] > 0.10:
            result.append(articlesDict[eve[1]])
    if len(result) >= 8:
        result = result[0:8]
    return {"result": json.dumps(result)}
