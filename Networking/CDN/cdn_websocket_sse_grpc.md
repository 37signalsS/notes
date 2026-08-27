# CDN — WebSocket, SSE и gRPC

## Определения

- **WebSocket (RFC 6455)**: Протокол двунаправленной связи поверх TCP. Устанавливается через HTTP- handshake (Upgrade), затем работает как полноценный дуплексный канал. Используется для чатов, уведомлений, онлайн-игр.
- **Server-Sent Events (SSE / EventSource)**: Однонаправленный (server → client) протокол доставки событий поверх HTTP. Использует `text/event-stream` формат. Автоматическое переподключение через `Last-Event-ID`.
- **gRPC**: Высокопроизводительный RPC-фреймворк на базе HTTP/2 и Protocol Buffers. Поддерживает streaming (unary, server-streaming, client-streaming, bidirectional).
- **Long-Polling**: Техника эмуляции push-уведомлений: клиент отправляет запрос, сервер держит его открытым до появления нового события или таймаута.
- **WebSocket Keep-Alive**: Механизм поддержания активного WebSocket-соединения через периодические ping/pong-帧ы.
- **WebSocket Through CDN**: Проксирование WebSocket-соединений через CDN с терминацией TLS на edge-узле и пересылкой на Origin.
- **SSE Through CDN**: Доставка событий от Origin через CDN с использованием HTTP/1.1 chunked encoding.
- **gRPC Through CDN**: Проксирование gRPC-вызовов через CDN с поддержкой HTTP/2 и Protocol Buffers.
- **WebSocket Timeout**: Максимальное время жизни WebSocket-соединения на CDN. Cloudflare: 100 сек (Free), 1800 сек (Enterprise).
- **Connection Upgrade (101 Switching Protocols)**: HTTP-ответ сервера, подтверждающий переключение на WebSocket.

---

## Теория

### WebSocket через CDN

**Как работает:**
1. Клиент отправляет HTTP-запрос с заголовком `Upgrade: websocket`.
2. CDN проксирует запрос на Origin.
3. Origin отвечает `101 Switching Protocols`.
4. CDN устанавливает двунаправленный канал между клиентом и Origin.
5. Все последующие кадры WebSocket проходят через CDN без HTTP-заголовков.

**Особенности CDN:**
- CDN хранит соединение в памяти (не в кэше).
- Трафик WebSocket не кэшируется.
- CDN может терминировать TLS и переподключаться к Origin через HTTP/2 (внутренний мультиплексинг).

**Схема:**
```
[Клиент] ←TLS→ [CDN Edge] ←TCP/HTTP2→ [Origin]
   ↑                ↑                       ↑
   WebSocket        Proxy (в памяти)        WebSocket
   Connection       на edge-узле            Handler
```

**Ограничения CDN:**

| Параметр | Cloudflare | Fastly | Akamai | CloudFront |
| :--- | :--- | :--- | :--- | :--- |
| **Max Connection** | 10,000/домен | 100,000/сервис | Ограничение по плану | Нет поддержки WS |
| **Timeout** | 100 сек (Free), 1800 сек (Enterprise) | 3600 сек | 3600 сек | N/A |
| **Max Frame Size** | 64 КБ (Free), 1 МБ (Enterprise) | Ограничение backend | Ограничение backend | N/A |
| **Compression (permessage-deflate)** | Да | Да | Да | N/A |

### SSE через CDN

**Как работает:**
1. Клиент отправляет обычный HTTP GET-запрос с `Accept: text/event-stream`.
2. Origin отвечает `200 OK` с `Content-Type: text/event-stream`.
3. CDN проксирует стриминговые данные клиенту через chunked encoding.
4. При реконнекте клиент отправляет `Last-Event-ID` для получения пропущенных событий.

**Особенности CDN:**
- SSE использует обычный HTTP, поэтому CDN может кэшировать (если настроено) или проксировать.
- Важно отключать кэширование для SSE: `Cache-Control: no-cache, no-store`.
- CDN автоматически добавляет `Connection: keep-alive` и отключает сжатие для стриминга.

**Схема:**
```
[Клиент] ←HTTP→ [CDN Edge] ←HTTP/1.1 chunked→ [Origin]
   ↑                ↑                              ↑
   EventSource      Stream Proxy                 SSE Handler
   (browser)        (no-cache)                   (text/event-stream)
```

**Преимущество SSE перед WebSocket:**
- Использует обычный HTTP → проще через прокси и CDN.
- Автоматическое переподключение (built-in).
- Поддержка `Last-Event-ID` для восстановления.
- Работает через HTTP/2 multiplexing.

**Недостаток SSE:**
- Только server → client (однонаправленный).
- Для двустороннего общения нужен WebSocket или gRPC.

### gRPC через CDN

**Как работает:**
1. Клиент отправляет HTTP/2 POST-запрос с `Content-Type: application/grpc`.
2. CDN проксирует HTTP/2 соединение на Origin.
3. Origin обрабатывает Protocol Buffers и возвращает ответ.

**Особенности CDN:**
- Требует HTTP/2 (не HTTP/1.1).
- CDN должен поддерживать проксирование HTTP/2 (не все CDN).
- gRPC-стриминг (bidirectional) требует persistent connection.
- CDN не кэширует gRPC-ответы (POST-методы).

**Поддержка gRPC CDN:**
- **Cloudflare**: Полная поддержка gRPC (HTTP/2) с 2020 года.
- **Fastly**: Полная поддержка через Compute@Edge.
- **Akamai**: Ограниченная поддержка (только unary RPC).
- **CloudFront**: Не поддерживает gRPC (2026).

### Сравнение протоколов

| Протокол | Направление | Transport | Кэширование CDN | Поддержка CDN |
| :--- | :--- | :--- | :--- | :--- |
| **WebSocket** | Bidirectional | TCP | Нет (streaming) | Cloudflare, Fastly, Akamai |
| **SSE** | Server → Client | HTTP/1.1 | Нет (no-cache) | Все CDN |
| **gRPC** | Bidirectional | HTTP/2 | Нет (POST) | Cloudflare, Fastly |
| **Long-Polling** | Bidirectional (эмуляция) | HTTP | Да (короткий TTL) | Все CDN |
| **HTTP/2 Push** | Server → Client | HTTP/2 | Да (предзагрузка) | Все CDN |

---

## Практика

### Cloudflare: WebSocket

```javascript
// Клиент: подключение к WebSocket через CDN
const ws = new WebSocket('wss://ws.example.com/chat');

ws.onopen = () => {
  console.log('WebSocket подключен через CDN');
  ws.send(JSON.stringify({ type: 'join', room: 'general' }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Получено:', data);
};

ws.onclose = (event) => {
  console.log('WebSocket закрыт:', event.code, event.reason);
  // Автоматическое переподключение через 5 секунд
  setTimeout(() => reconnect(), 5000);
};

// Heartbeat для поддержания соединения
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  }
}, 30000);
```

**Nginx: WebSocket Proxy:**
```nginx
# WebSocket proxy
location /ws/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";

    # Таймауты WebSocket
    proxy_read_timeout 86400s;  # 24 часа
    proxy_send_timeout 86400s;

    # Буферизация (отключить для real-time)
    proxy_buffering off;

    # Реальный IP клиента
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

### Cloudflare: SSE

```javascript
// Клиент: SSE через CDN
const eventSource = new EventSource('https://api.example.com/events');

eventSource.onmessage = (event) => {
  console.log('Событие:', JSON.parse(event.data));
};

eventSource.onerror = (error) => {
  console.log('Ошибка SSE:', error);
  // Автоматическое переподключение (built-in)
};

// Восстановление через Last-Event-ID
eventSource.addEventListener('important', (event) => {
  const id = event.lastEventId;
  const data = JSON.parse(event.data);
  console.log(`Событие ${id}:`, data);
});
```

**Origin: SSE endpoint (Node.js):**
```javascript
// server.js
const http = require('http');

http.createServer((req, res) => {
  if (req.url === '/events') {
    // Заголовки для SSE через CDN
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',  // Отключить буферизацию Nginx
      'Access-Control-Allow-Origin': '*'
    });

    // Отправка событий
    let eventId = 0;
    const interval = setInterval(() => {
      res.write(`id: ${eventId}\n`);
      res.write(`data: ${JSON.stringify({ time: Date.now(), id: eventId })}\n\n`);
      eventId++;
    }, 1000);

    req.on('close', () => {
      clearInterval(interval);
    });
  }
}).listen(3000);
```

**Cloudflare: Отключение буферизации для SSE:**
```nginx
# Nginx: конфигурация для SSE через CDN
location /events {
    proxy_pass http://backend_sse;
    proxy_buffering off;              # Критично для SSE
    proxy_cache off;                  # Не кэшировать
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;

    # Отключить gzip для SSE (chunked не сжимается)
    gzip off;
}
```

### Cloudflare: gRPC

```protobuf
// proto/chat.proto
syntax = "proto3";
package chat;

service ChatService {
  rpc SendMessage (MessageRequest) returns (MessageResponse);
  rpc StreamMessages (StreamRequest) returns (stream Message);
}

message MessageRequest {
  string user_id = 1;
  string room_id = 2;
  string content = 3;
}

message MessageResponse {
  bool success = 1;
  string message_id = 2;
}

message StreamRequest {
  string room_id = 1;
}

message Message {
  string id = 1;
  string user_id = 2;
  string content = 3;
  int64 timestamp = 4;
}
```

**Клиент gRPC через CDN (Go):**
```go
package main

import (
    "context"
    "log"
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials"
    pb "example.com/chat"
)

func main() {
    // gRPC через CDN (Cloudflare)
    // Cloudflare требует правильного SNI и Host
    creds, _ := credentials.NewClientTLSFromFile("cloudflare.pem", "")

    conn, err := grpc.Dial(
        "grpc.example.com:443",  // CDN endpoint
        grpc.WithTransportCredentials(creds),
        grpc.WithAuthority("grpc.example.com"),  // Host header
    )
    if err != nil {
        log.Fatalf("Did not connect: %v", err)
    }
    defer conn.Close()

    client := pb.NewChatServiceClient(conn)

    // Unary RPC
    resp, err := client.SendMessage(context.Background(), &pb.MessageRequest{
        UserId:  "user-1",
        RoomId:  "general",
        Content: "Hello through CDN!",
    })
    if err != nil {
        log.Fatalf("Error: %v", err)
    }
    log.Printf("Message sent: %s", resp.MessageId)

    // Server-streaming RPC
    stream, err := client.StreamMessages(context.Background(), &pb.StreamRequest{
        RoomId: "general",
    })
    if err != nil {
        log.Fatalf("Stream error: %v", err)
    }
    for {
        msg, err := stream.Recv()
        if err != nil {
            break
        }
        log.Printf("Received: %s from %s", msg.Content, msg.UserId)
    }
}
```

**Nginx: gRPC Proxy:**
```nginx
# gRPC proxy (требует Nginx 1.13.10+)
server {
    listen 443 ssl http2;

    location /chat.ChatService/ {
        grpc_pass grpc://backend_grpc;

        # Таймауты gRPC
        grpc_connect_timeout 5s;
        grpc_read_timeout 60s;
        grpc_send_timeout 10s;

        # Обработка ошибок
        error_page 502 = /grpc_error;
        error_page 504 = /grpc_timeout;
    }

    location = /grpc_error {
        default_type application/grpc;
        add_header grpc-status 14;
        add_header grpc-message "Service unavailable";
        return 204;
    }
}
```

### Тестирование WebSocket через CDN

```bash
# Проверка WebSocket handshake
curl -sD- \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "https://ws.example.com/chat"
# → HTTP/1.1 101 Switching Protocols
# → Upgrade: websocket
# → Connection: Upgrade
# → Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=

# Проверка через websocat
websocat wss://ws.example.com/chat
# Подключение к WebSocket через CDN

# Проверка SSE
curl -N "https://api.example.com/events" \
  -H "Accept: text/event-stream"
# → data: {"time":1692960000000,"id":0}
# → data: {"time":1692960001000,"id":1}

# Проверка gRPC
grpcurl -plaintext grpc.example.com:443 list
# → chat.ChatService
```

### Мониторинг WebSocket и SSE

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| **Active Connections** | Количество активных WebSocket/SSE соединений | Мониторинг |
| **Connection Duration** | Среднее время жизни соединения | >5 мин |
| **Message Rate** | Количество сообщений в секунду | Мониторинг пиков |
| **Error Rate** | Доля ошибок соединения | <0.1% |
| **Reconnect Rate** | Частота переподключений | <1/час |
| **Bandwidth** | Потребление трафика WebSocket/SSE | Мониторинг |

---

## Дополнительная информация

### Типичные ошибки и их решение

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **WebSocket Timeout** | Соединение разрывается через 100 сек | Увеличить timeout (Enterprise) или использовать Heartbeat |
| **SSE Buffering** | События приходят с задержкой | Отключить `proxy_buffering` в Nginx, использовать `X-Accel-Buffering: no` |
| **gRPC 502** | CDN возвращает Bad Gateway | Убедиться, что Origin поддерживает HTTP/2 |
| **CORS для SSE** | Браузер блокирует EventSource | Добавить `Access-Control-Allow-Origin` в Origin |
| **WebSocket и Load Balancer** | Соединения нестабильны | Использоватьsticky sessions или IP Hash |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — поддержка протоколов и Edge Computing.
- **[HTTP/3 и QUIC](cdn_overview.md#поддержка-http3-и-quic)** — транспорт для WebSocket и gRPC.
- **[Health Checks](cdn_origin_health_checks.md)** — мониторинг WebSocket-серверов.
- **[Edge Computing](../../Concepts/edge_computing_overview.md)** — выполнение логики на CDN.
