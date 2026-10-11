# S3: pre-signed POST и browser uploads

**Актуально для:** S3 API, Ceph RGW (Squid 19.x / Tentacle 20.x)

---

## 1. Определения

**Pre-signed POST** — механизм S3, позволяющий клиентам (обычно браузерам) загружать объекты напрямую в bucket через HTML-форму, без передачи credentials на фронтенд. Backend генерирует подписанную форму с ограничениями (policy), а браузер отправляет объект по `multipart/form-data`.

**Browser upload** — загрузка файла из браузера напрямую в S3, минуя backend-сервер. Снижает нагрузку на backend и ускоряет загрузку за счёт прямого соединения с S3.

**Policy document** — JSON-документ, ограничивающий параметры загрузки: размер, тип файла, ключ, время действия. Подписывается credentials владельца bucket.

**Field (form field)** — скрытое поле HTML-формы, содержащее подписанные параметры (`key`, `policy`, `signature`, `x-amz-*`). Браузер отправляет их вместе с файлом.

**Content-MD5** — MD5-хеш содержимого объекта. В pre-signed POST используется как precondition для проверки целостности.

**Condition** — ограничение в policy document. Поддерживаемые условия:
- `eq` — равенство
- `starts-with` — префикс
- `content-length-range` — диапазон размера файла
- `content-type` — MIME-тип

**CORS (Cross-Origin Resource Sharing)** — механизм, позволяющий браузерам выполнять запросы к S3 bucket с других origins. Критично для web-приложений, загружающих файлы напрямую в S3. В Ceph RGW настраивается через `put-bucket-cors` или `radosgw-admin`.

**Access Logging** — механизм записи всех запросов к бакету в целевой бакет. Позволяет отследить, кто, когда и что загрузил.

**S3 Event Notification** — механизм уведомления внешних систем (SQS, SNS, Lambda) о событиях в bucket: `s3:ObjectCreated:Post`, `s3:ObjectCreated:Put` и др.

---

## 2. Базовые концепции

### 2.1 Зачем pre-signed POST вместо pre-signed URL

| Критерий | Pre-signed URL | Pre-signed POST |
|----------|---------------|-----------------|
| **Тип запроса** | PUT Object | multipart/form-data |
| **Контроль размера** | Нет | Да (`content-length-range`) |
| **Контроль MIME** | Нет | Да (`content-type`) |
| **Контроль ключа** | В URL | В policy (`starts-with`) |
| **Использование** | Программные клиенты | Браузеры, мобильные приложения |
| **Form fields** | Нет | Да (дополнительные метаданные) |

**Когда использовать POST:**
- Browser uploads (`input type=file`).
- Ограничение размера/типа файла на стороне S3.
- Необходимость передать дополнительные метаданные без backend-проксирования.
- Мобильные приложения, где прямая загрузка в S3 экономит трафик.

### 2.2 Как работает pre-signed POST

```
┌─────────┐        1. Генерация policy         ┌─────────┐
│ Frontend│────────────────────────────────────▶│ Backend │
│ (Browser)│                                   │ (S3 API)│
└─────────┘                                   └────┬────┘
       ▲                                             │ 2. Возврат подписанных полей
       │                                             ▼
       │              3. Загрузка файла             ┌─────────┐
       └────────────────────────────────────────────│ S3      │
                                                    │ (direct)│
                                                    └─────────┘
```

1. Frontend запрашивает у backend'а credentials для загрузки.
2. Backend генерирует `policy` + `signature` с ограничениями и возвращает их frontend.
3. Frontend отправляет `multipart/form-data` запрос напрямую в S3.
4. S3 проверяет подпись и policy. При соответствии — объект загружен.

**Важно:** Credentials backend'а никогда не попадают на frontend. Подпись ограничена по времени и параметрам.

### 2.3 Policy document structure

```json
{
  "expiration": "2026-12-31T23:59:59.000Z",
  "conditions": [
    {"bucket": "my-app-uploads"},
    ["starts-with", "$key", "uploads/"],
    ["content-length-range", 1048576, 10485760],
    ["starts-with", "$content-type", "image/"],
    {"x-amz-server-side-encryption": "AES256"},
    ["starts-with", "$x-amz-meta-uploaded-by", ""]
  ]
}
```

**Поля policy:**
- `expiration` — время действия формы (UTC). Рекомендуется: 5–60 минут.
- `conditions` — массив ограничений. S3 проверяет их в точности.

**Base64-encoded policy:**
```bash
# Кодирование policy в base64
echo '{"expiration":"2026-12-31T23:59:59.000Z","conditions":[...]}' | base64
# → eyJleHBpcmF0aW9uIjoi...'
```

### 2.4 Подпись policy

Signature = Base64( HMAC-SHA256( secret_key, base64_policy ) )

```python
import hmac
import hashlib
import base64

def sign_policy(policy_b64, secret_key):
    signature = hmac.new(
        secret_key.encode('utf-8'),
        policy_b64.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')
```

### 2.5 Ceph RGW и pre-signed POST

Ceph RGW поддерживает pre-signed POST в соответствии со спецификацией S3 API. POST Object загружен в RGW. Для корректной работы необходимо:

- RGW daemon (Squid 19.x / Tentacle 20.x) с включённым S3 API (`rgw_enable_apis = s3,s3control`)
- Bucket с ACL/policy, разрешающей `s3:PutObject` для вызывающего пользователя
- CORS, настроенный для домена фронтенда (если загрузка из браузера)
- Доступность RGW endpoint из сети клиента

Специального флага `rgw generate presigned post urls` в `ceph.conf` не существует. Presigned POST работает по умолчанию при корректной S3-аутентификации.

---

## 3. Практические сценарии

### 3.1 Предварительные требования

- Ceph кластер с RGW daemon (Squid 19.x / Tentacle 20.x)
- AWS CLI 2.x, boto3, или совместимый S3 SDK/клиент
- Bucket с включённым версионированием (опционально, но рекомендуется)
- CORS, настроенный на bucket для домена фронтенда
- IAM-пользователь или RGW-пользователь с правами `s3:PutObject` на целевой bucket
- Backend-сервер с SDK для генерации подписанных форм
- Для браузерных загрузок: HTTPS endpoint и валидный TLS-сертификат

### 3.2 Генерация pre-signed POST (Python + boto3)

```python
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client(
    's3',
    region_name='eu-central-1',
    endpoint_url='http://rgw:7480',
    aws_access_key_id='...',
    aws_secret_access_key='...'
)

# Генерация pre-signed POST
response = s3_client.generate_presigned_post(
    Bucket='my-app-uploads',
    Key='uploads/${filename}',
    Fields={
        'x-amz-server-side-encryption': 'AES256',
        'x-amz-meta-uploaded-by': 'web-client'
    },
    Conditions=[
        {'bucket': 'my-app-uploads'},
        ['starts-with', '$key', 'uploads/'],
        ['content-length-range', 1048576, 10485760],  # 1 MB – 10 MB
        ['starts-with', '$content-type', 'image/'],
        {'x-amz-server-side-encryption': 'AES256'},
        ['starts-with', '$x-amz-meta-uploaded-by', '']
    ],
    ExpiresIn=600  # 10 минут
)

# response содержит:
# - url: endpoint для загрузки
# - fields: словарь с policy, signature, key, x-amz-* полями
print(response['url'])
print(response['fields'])
```

**Валидация:**
```python
# Проверка структуры ответа
assert 'url' in response
assert 'fields' in response
assert 'key' in response['fields']
assert 'policy' in response['fields']
assert 'signature' in response['fields'] or 'x-amz-signature' in response['fields']
```

### 3.3 HTML-форма для загрузки

```html
<!DOCTYPE html>
<html>
<body>
  <h1>Upload File</h1>
  <form id="upload-form" enctype="multipart/form-data">
    <input type="file" id="file-input" name="file" required>
    <button type="submit">Upload</button>
  </form>

  <script>
    async function getPresignedPost() {
      const response = await fetch('/api/s3/presigned-post');
      return await response.json();
    }

    document.getElementById('upload-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById('file-input');
      const file = fileInput.files[0];

      const {url, fields} = await getPresignedPost();

      const formData = new FormData();
      // Важно: поля из presigned POST добавляются ПЕРВЫМИ
      Object.entries(fields).forEach(([key, value]) => {
        formData.append(key, value);
      });
      // Файл добавляется ПОСЛЕДНИМ — это требование S3
      formData.append('file', file);

      const uploadResponse = await fetch(url, {
        method: 'POST',
        body: formData
        // НЕ устанавливайте Content-Type вручную!
        // Браузер сам добавит multipart/form-data с boundary.
      });

      if (uploadResponse.ok) {
        console.log('Upload successful');
      } else {
        const errorText = await uploadResponse.text();
        console.error('Upload failed:', errorText);
      }
    });
  </script>
</body>
</html>
```

**Валидация:**
```bash
# Проверка через curl
curl -X POST "$UPLOAD_URL" \
  -F "key=uploads/test.jpg" \
  -F "policy=BASE64_POLICY" \
  -F "signature=SIGNATURE" \
  -F "x-amz-algorithm=AWS4-HMAC-SHA256" \
  -F "x-amz-credential=..." \
  -F "x-amz-date=..." \
  -F "file=@test.jpg"
```

### 3.4 Backend: Flask endpoint для генерации POST

```python
from flask import Flask, jsonify, request
from flask_limiter import Limiter
import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)

# Rate limiting: 30 запросов в минуту на IP
limiter = Limiter(
    app=app,
    key_func=lambda: request.remote_addr,
    default_limits=["30 per minute"]
)

s3_client = boto3.client(
    's3',
    region_name='eu-central-1',
    endpoint_url='http://rgw:7480'
)

@app.route('/api/s3/presigned-post', methods=['GET'])
@limiter.limit("30 per minute")
def generate_presigned_post():
    # ВАЛИДАЦИЯ: проверка сессии/авторизации обязательна!
    user_id = request.headers.get('X-User-ID')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        response = s3_client.generate_presigned_post(
            Bucket='my-app-uploads',
            Key=f'uploads/{user_id}/${{filename}}',
            Fields={
                'x-amz-server-side-encryption': 'AES256',
                'x-amz-meta-uploaded-by': user_id
            },
            Conditions=[
                {'bucket': 'my-app-uploads'},
                ['starts-with', '$key', f'uploads/{user_id}/'],
                ['content-length-range', 1048576, 10485760],
                ['starts-with', '$content-type', 'image/'],
                {'x-amz-server-side-encryption': 'AES256'},
                ['starts-with', '$x-amz-meta-uploaded-by', user_id]
            ],
            ExpiresIn=600
        )
        return jsonify(response)
    except ClientError as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False)
```

**Валидация:**
```bash
# Проверка авторизации на endpoint
curl -H "X-User-ID: test-user" http://localhost:5000/api/s3/presigned-post
# → {"url": "...", "fields": {...}}

# Без заголовка X-User-ID
curl http://localhost:5000/api/s3/presigned-post
# → {"error": "Unauthorized"}, 401
```

### 3.5 Backend: Go (aws-sdk-go-v2)

```go
import (
    "context"
    "time"
    "github.com/aws/aws-sdk-go-v2/service/s3"
    "github.com/aws/aws-sdk-go-v2/service/s3/presign"
)

func GeneratePresignedPost(
    ctx context.Context,
    presignClient *presign.Client,
    bucket, keyPrefix, userID string,
) (*s3.PresignedPostResponse, error) {
    resp, err := presignClient.PresignPost(ctx, &s3.PresignPostInput{
        Bucket: aws.String(bucket),
        Key:    aws.String(keyPrefix + "/${filename}"),
        Conditions: []interface{}{
            map[string]string{"bucket": bucket},
            []string{"starts-with", "$key", keyPrefix + "/"},
            []string{"content-length-range", "1048576", "10485760"},
        },
        Fields: map[string]string{
            "x-amz-server-side-encryption": "AES256",
            "x-amz-meta-uploaded-by":       userID,
        },
        Expires: 600 * time.Second,
    })

    return resp, err
}
```

**Валидация:**
```go
// Проверка результата
if resp == nil || resp.URL == "" {
    return errors.New("empty presigned post response")
}
if len(resp.Fields) == 0 {
    return errors.New("no fields in presigned post")
}
```

### 3.6 CORS для bucket

CORS обязателен для браузерных загрузок. В Ceph RGW настраивается через S3 API.

```bash
# Настройка CORS через aws-cli
aws s3api put-bucket-cors \
  --bucket my-app-uploads \
  --cors-configuration '{
    "CORSRules": [
      {
        "AllowedOrigins": ["https://app.example.com"],
        "AllowedMethods": ["PUT", "POST", "GET", "HEAD"],
        "AllowedHeaders": [
          "Content-Type",
          "Content-MD5",
          "x-amz-server-side-encryption",
          "x-amz-meta-*"
        ],
        "ExposeHeaders": ["ETag", "x-amz-version-id"],
        "MaxAgeSeconds": 3600
      }
    ]
  }' \
  --endpoint-url http://rgw:7480

# Проверка CORS
aws s3api get-bucket-cors \
  --bucket my-app-uploads \
  --endpoint-url http://rgw:7480
```

**Валидация:**
```bash
# Проверка через curl
curl -X OPTIONS \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  http://rgw:7480/my-app-uploads/ \
  -I
# Должен вернуться:
# Access-Control-Allow-Origin: https://app.example.com
# Access-Control-Allow-Methods: PUT, POST, GET, HEAD
```

### 3.7 S3 Event Notifications для post-upload обработки

После успешной загрузки через pre-signed POST можно автоматически обработать объект:

```bash
# Настройка уведомлений через S3 API
aws s3api put-bucket-notification-configuration \
  --bucket my-app-uploads \
  --notification-configuration '{
    "TopicConfigurations": [
      {
        "TopicArn": "arn:aws:sns:us-east-1:000000000000:upload-events",
        "Events": ["s3:ObjectCreated:Post"],
        "Filter": {
          "Key": {
            "FilterRules": [
              {"Name": "prefix", "Value": "uploads/"},
              {"Name": "suffix", "Value": ".jpg"}
            ]
          }
        }
      }
    ]
  }' \
  --endpoint-url http://rgw:7480
```

**В Ceph RGW уведомления поддерживаются для:**
- SQS (через `radosgw-notification` или REST API)
- AMQP/RabbitMQ
- Kafka (с версии Pacific)
- HTTP(S) webhooks

### 3.8 Lifecycle policies для uploaded объектов

```bash
# Автоматический переход в Infrequent Access через 30 дней
# и удаление через 365 дней
aws s3api put-bucket-lifecycle-configuration \
  --bucket my-app-uploads \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "uploads-cleanup",
        "Status": "Enabled",
        "Prefix": "uploads/",
        "Transitions": [
          {"Days": 30, "StorageClass": "STANDARD_IA"}
        ],
        "Expiration": {"Days": 365}
      }
    ]
  }' \
  --endpoint-url http://rgw:7480
```

### 3.9 Monitoring и audit uploads

```bash
# Включение access logging через RGW
radosgw-admin bucket stats --bucket="my-app-uploads"

# Просмотр логов RGW
grep "POST.*my-app-uploads" /var/log/ceph/radosgw.*.log | tail -50

# Проверка размера bucket
radosgw-admin bucket stats --bucket="my-app-uploads" --format=json

# Audit через Ceph Dashboard (Squid+)
# Metrics → RGW → Bucket → Operations → POST
```

---

## 4. Валидация

### 4.1 Проверка корректности pre-signed POST

```bash
# 1. Проверка подписи policy (Python)
python3 -c "
import hmac, hashlib, base64
policy_b64 = 'BASE64_POLICY'
secret_key = 'SECRET_KEY'
sig = base64.b64encode(
    hmac.new(secret_key.encode(), policy_b64.encode(), hashlib.sha256).digest()
).decode()
print('Signature:', sig)
"

# 2. Проверка expiresIn
# Рекомендуется: 300–1800 секунд. >3600 — редко оправдано.
python3 -c "
expires_in = 600
print(f'ExpiresIn: {expires_in}s ({expires_in/60} min)')
assert 300 <= expires_in <= 1800, 'ExpiresIn вне безопасного диапазона'
"

# 3. Проверка условий policy
# Убедитесь, что все x-amz-* поля из Fields имеют соответствующие условия
python3 -c "
fields = {'x-amz-server-side-encryption': 'AES256'}
conditions = [
    {'bucket': 'my-app-uploads'},
    ['starts-with', '$key', 'uploads/'],
]
# Добавьте условие для каждого x-amz-* поля
for field in fields:
    if not any(
        (isinstance(c, dict) and field in c) or
        (isinstance(c, list) and len(c) > 1 and c[1] == f'\${field}')
        for c in conditions
    ):
        print(f'Предупреждение: поле {field} не имеет условия в policy')
"
```

### 4.2 Проверка CORS

```bash
# OPTIONS preflight request
curl -X OPTIONS \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type, x-amz-server-side-encryption" \
  http://rgw:7480/my-app-uploads/ \
  -I

# Ожидаемые заголовки:
# HTTP/1.1 200 OK
# Access-Control-Allow-Origin: https://app.example.com
# Access-Control-Allow-Methods: PUT, POST, GET, HEAD
# Access-Control-Max-Age: 3600
```

### 4.3 Проверка загрузки через curl

```bash
# Получение presigned POST (через backend)
curl http://localhost:5000/api/s3/presigned-post \
  -H "X-User-ID: test-user" > /tmp/post.json

# Извлечение полей
python3 -c "
import json
with open('/tmp/post.json') as f:
    data = json.load(f)
print('URL:', data['url'])
for k, v in data['fields'].items():
    print(f'{k}={v}')
" > /tmp/fields.txt

# Загрузка файла
curl -X POST "$(python3 -c "import json; print(json.load(open('/tmp/post.json'))['url')")" \
  -F "key=uploads/test.jpg" \
  -F "policy=$(grep '^policy=' /tmp/fields.txt | cut -d= -f2-)" \
  -F "signature=$(grep '^signature=' /tmp/fields.txt | cut -d= -f2-)" \
  -F "x-amz-algorithm=AWS4-HMAC-SHA256" \
  -F "x-amz-credential=$(grep '^x-amz-credential=' /tmp/fields.txt | cut -d= -f2-)" \
  -F "x-amz-date=$(grep '^x-amz-date=' /tmp/fields.txt | cut -d= -f2-)" \
  -F "x-amz-security-token=$(grep '^x-amz-security-token=' /tmp/fields.txt | cut -d= -f2-)" \
  -F "file=@test.jpg"
```

---

## 5. Сценарии инцидентов

### 5.1 Сценарий: 403 Forbidden при POST

**Симптомы:** Браузер возвращает 403 при загрузке.

**Диагностика:**
```bash
# 1. Проверка CORS preflight
curl -X OPTIONS -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  http://rgw:7480/my-app-uploads/ -I

# 2. Проверка подписи policy
# Убедитесь, что secret_key backend'а совпадает с ключом RGW-пользователя

# 3. Проверка expiresIn
# Убедитесь, что форма не истекла

# 4. Проверка условий
# Каждое x-amz-* поле из Fields должно иметь условие в Conditions
```

**Решение:**
- Убедитесь, что CORS настроен корректно.
- Проверьте, что `x-amz-*` поля соответствуют условиям в policy.
- Убедитесь, что `Content-Type` в запросе совпадает с условием.

### 5.2 Сценарий: Загрузка зависает

**Симптомы:** Файл не загружается, браузер показывает "Pending" indefinitely.

**Диагностика:**
```bash
# 1. Проверка CORS
grep "Access-Control" /var/log/nginx/access.log | tail -20

# 2. Проверка размера файла
ls -lh test.jpg

# 3. Проверка network в браузере
# Tab Network → POST запрос → Response Headers
```

**Решение:**
- Настройте CORS на bucket.
- Убедитесь, что размер файла входит в `content-length-range`.
- Проверьте, что RGW endpoint доступен из сети клиента.

### 5.3 Сценарий: Неверный MIME type

**Симптомы:** S3 возвращает 403, хотя файл загружается корректно.

**Диагностика:**
```bash
# Проверка Content-Type в запросе
curl -X POST "$UPLOAD_URL" \
  -F "key=uploads/test.jpg" \
  -F "file=@test.jpg" \
  -F "Content-Type=image/jpeg" \
  -I
```

**Решение:**
- Используйте `starts-with` вместо `eq` для `content-type` в policy.
- Убедитесь, что браузер отправляет правильный MIME type.

### 5.4 Сценарий: Tenanted client не работает

**Симптомы:** Presigned POST генерируется, но загрузка возвращает 403 для tenanted пользователей.

**Диагностика:**
```bash
# Проверка tenant в credentials
aws s3api list-buckets \
  --endpoint-url http://rgw:7480 \
  --profile tenant-user

# Проверка ключа bucket
radosgw-admin bucket stats --bucket="tenant$my-app-uploads"
```

**Решение:**
- Tenanted bucket'ы имеют имя вида `tenant$bucket`. Убедитесь, что `Bucket` в `generate_presigned_post` включает tenant prefix.
- Известный баг в Ceph RGW: presigned POST для tenanted клиентов может не работать. Workaround: используйте не-tenanted бакет или подождите исправления.

### 5.5 Сценарий: File field не последний

**Симптомы:** S3 возвращает 403 или 400 при загрузке.

**Диагностика:**
```bash
# Проверка порядка полей в multipart/form-data
curl -X POST "$UPLOAD_URL" \
  -F "file=@test.jpg" \
  -F "key=uploads/test.jpg" \
  -F "policy=..." \
  -F "signature=..."
# → 403 Forbidden

curl -X POST "$UPLOAD_URL" \
  -F "key=uploads/test.jpg" \
  -F "policy=..." \
  -F "signature=..." \
  -F "file=@test.jpg"
# → 204 No Content
```

**Решение:**
- В `FormData` JavaScript поля из `presignedPost.fields` должны добавляться ПЕРВЫМИ.
- Поле `file` должно быть ПОСЛЕДНИМ.

---

## 6. Best Practices

1. **Ограничьте время жизни policy:** 5–60 минут. Никогда не делайте > 1 час для browser uploads.
2. **Используйте `content-length-range`** для защиты от DoS. Ограничьте максимальный размер на уровне S3.
3. **Принудительно включайте шифрование** через `x-amz-server-side-encryption` в policy.
4. **Валидируйте MIME-type** на стороне backend перед выдачей policy. Не полагайтесь только на фронтенд.
5. **Используйте случайные суффиксы в ключе** (`${filename}` или UUID) для избежания overwrite.
6. **Настройте CORS** на bucket для домена вашего фронтенда. Всегда ограничивайте `AllowedOrigins` конкретными доменами.
7. **Добавьте авторизацию на backend endpoint** для генерации presigned POST. Никогда не делайте endpoint публичным без rate limiting и auth.
8. **Rate-limit endpoint** для генерации presigned POST (например, 30 запросов в минуту на IP).
9. **Используйте `x-amz-meta-*` поля** с user_id, session_id для трассировки.
10. **Мониторьте uploads** через RGW access logging или inventory reports для аудита.
11. **Настройте S3 Event Notifications** для автоматической обработки загруженных объектов.
12. **Документируйте runbook** для отката policy/credentials при компрометации.
13. **Для production** добавьте lifecycle policies для управления стоимостью хранения.
14. **Тестируйте с ngrok/localstack** перед production deploy.
15. **Никогда не передавайте secret key на frontend.** Генерация policy только на backend.

---

## 7. См. также

- [Amazon S3 — архитектура, протокол и эксплуатация](./overview.md)
- [S3: безопасность, шифрование и compliance](./security.md)
- [S3: мониторинг, алерты и cost optimization](./monitoring.md)
- [S3: распространённые операции CLI и эксплуатация](./cli-operations.md)
