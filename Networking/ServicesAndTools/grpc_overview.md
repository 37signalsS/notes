# gRPC — обзор фреймворка

## Определения

**gRPC (gRPC Remote Procedure Calls)** — это высокопроизводительный универсальный фреймворк для удалённого вызова процедур (RPC) с открытым исходным кодом, изначально разработанный Google. Он позволяет приложениям взаимодействовать друг с другом так же просто, как при вызове локальных методов, абстрагируя детали сетевого обмена и сериализации.

gRPC является стандартом для межсервисного взаимодействия (East-West traffic) в микросервисных архитектурах, обеспечивая высокую пропускную способность и низкие задержки.

**Connect RPC** — легковесная альтернатива традиционному gRPC, разработанная Buf Build. Поддерживает три протокола: gRPC, gRPC-Web и собственный Connect-протокол. Работает поверх `net/http` (Go), использует стандартные HTTP/1.1 и HTTP/2, JSON и Protobuf. Полностью совместима с gRPC-клиентами и серверами. Языки: Go, TypeScript, Swift, Kotlin, Dart, Python. Последняя версия: v1.20.0 (May 2026).

**Актуальность (2025–2026):**
*   **HTTP/3 (QUIC):** Полная поддержка в стабильных версиях библиотек (Go, C++, Rust). Решает проблему блокировки очереди (HOL) и обеспечивает бесшовную миграцию соединений (Connection Migration) при смене IP-адреса клиента.
*   **Model Context Protocol (MCP):** gRPC выбран основным транспортом для MCP, обеспечивая стандартизированный интерфейс взаимодействия между LLM-агентами и внешними инструментами.
*   **Post-Quantum TLS:** gRPC Core 1.83+ по умолчанию использует Post-Quantum Cryptography (ML-KEM) для обмена ключами в TLS.
*   **Protobuf Editions:** Новый механизм управления совместимостью (protobuf v23+), заменяющий `proto2`/`proto3` с явным указанием `edition = "2023"`.

**Версии (Aug 2026):**
| Компонент | Версия | Дата |
| :--- | :--- | :--- |
| gRPC Core (C/C++) | 1.83.0 | Jul 2026 |
| grpc-go | v1.83.2 | Aug 2026 |
| grpc-java | 1.72.x | Jul 2026 |
| Protobuf | v36.0 | Aug 2026 |
| Connect (Go) | v1.20.0 | May 2026 |

## Базовые концепции

### Protocol Buffers (Protobuf)

В основе gRPC лежит использование **Protocol Buffers** как языка описания интерфейсов (IDL) и формата сериализации.

*   **Контрактный подход:** API строго описывается в `.proto` файлах. Это единственный источник истины для клиентской и серверной сторон, на основе которого генерируется типизированный код.
*   **Бинарный формат:** Данные передаются в компактном бинарном виде. Отсутствие текстовых ключей (как в JSON) значительно снижает нагрузку на CPU при парсинге.
*   **Возможности Protobuf v3:**
    *   **Скалярные типы:** `int32`, `string`, `bool`, `bytes` и др.
    *   **Enums:** Перечисления для строго заданных наборов значений.
    *   **Maps:** Поддержка ассоциативных массивов.
    *   **Oneof:** Позволяет полю принимать один из нескольких заданных типов (аналог объединений).
    *   **Optional:** Явное отслеживание наличия значения в поле (возвращено в версии 3.15+).
    *   **Reserved:** Защита от повторного использования удалённых полей/имён.
    *   **Well-Known Types:** Стандартные типы `Timestamp`, `Duration`, `Any`, `FieldMask`, `Struct`.

### Транспорт и протоколы (HTTP/2 и HTTP/3)

gRPC использует продвинутые возможности современных транспортных протоколов:

*   **Мультиплексирование:** Отправка множества независимых потоков данных (Streams) через одно TCP/UDP соединение.
*   **Двунаправленная связь:** Клиент и сервер могут отправлять сообщения одновременно без ожидания подтверждения.
*   **Сжатие метаданных:** Использование HPACK (HTTP/2) или QPACK (HTTP/3) для минимизации оверхеда на заголовки.
*   **Flow Control:** Управление скоростью передачи на уровне потока и соединения (окна стека).
*   **QUIC (HTTP/3) преимущества:**
    *   **0-RTT Handshake:** Мгновенное возобновление соединения.
    *   **Устранение HOL Blocking:** Потеря одного пакета в потоке не блокирует остальные потоки в рамках того же соединения.
    *   **Connection Migration:** Бесшовная миграция соединения при смене сети (Wi-Fi → LTE).

### Типы взаимодействия (RPC Patterns)

1.  **Унарный (Unary):** Одиночный запрос — одиночный ответ (аналог REST).
2.  **Потоковый серверный (Server Streaming):** Клиент запрашивает данные, сервер возвращает поток (например, лента новостей или логи).
3.  **Потоковый клиентский (Client Streaming):** Клиент загружает большой объем данных потоком, сервер возвращает один результат.
4.  **Двунаправленный потоковый (Bidirectional Streaming):** Постоянный обмен данными в обе стороны (например, чаты или real-time игры).

### Архитектурные механизмы

*   **Интерцепторы (Interceptors):** Позволяют внедрять Middleware-логику (аутентификация, логирование, трассировка) до и после выполнения бизнес-логики. Аналог HTTP middleware.
*   **Отражение (Reflection):** Сервис, позволяющий динамически запрашивать схему API сервера. Необходим для работы инструментов вроде `grpcurl`.
*   **Крайние сроки (Deadlines):** Клиент указывает максимальное время ожидания ответа. Сервер может проверить остаток времени (`Context`) и прекратить обработку, если время истекло.
*   **Распрранение Deadline:** Deadline автоматически пропагируется через метаданные (`grpc-timeout`) на промежуточные сервисы. При каждом转发е должно вычитываться время, уже затраченное на предыдущем шаге.
*   **Отмена (Cancellation):** При отмене запроса клиентом (контекст `context.WithCancel`) отмена распространяется через `grpc-status 1` (CANCELLED) на весь цепочку вызовов.
*   **Service Config:** Конфигурация клиента, загружаемая из service config или name resolver. Определяет политики повторных попыток (Retry/Hedging), балансировку и параметры подключения.

### Повторные попытки и Hedging

*   **Retry Policy:** Клиент автоматически повторяет запрос при определённых статус-кодах (UNAVAILABLE, DEADLINE_EXCEEDED). Настраивается через Service Config:
    ```json
    {
      "methodConfig": [{
        "name": [{"service": "myservice"}],
        "retryPolicy": {
          "maxAttempts": 3,
          "initialBackoff": "0.1s",
          "maxBackoff": "1s",
          "backoffMultiplier": 2,
          "retryableStatusCodes": ["UNAVAILABLE"]
        }
      }]
    }
    ```
*   **Hedging Policy:** Отправка нескольких одинаковых запросов и использование первого успешного ответа. Снижает tail latency. Настраивается аналогично retry, но с `hedgingPolicy` вместо `retryPolicy`.

### Протоколы взаимодействия: gRPC, gRPC-Web, Connect

| Протокол | Транспорт | Браузеры | Балансировка | Формат |
| :--- | :--- | :--- | :--- | :--- |
| **gRPC** | HTTP/2 | Нет (требует прокси) | Стримовая | Protobuf, trailers |
| **gRPC-Web** | HTTP/1.1/2 | Да | По запросу | Protobuf/JSON, base64 |
| **Connect** | HTTP/1.1/2 | Да | По запросу | Protobuf/JSON, curl-friendly |

*   **gRPC-Web:** Реализация gRPC для браузеров. Требует Envoy/Connect-прокси для трансляции (proto trailers → HTTP trailers). Поддерживается `grpc/grpc-web`.
*   **Connect Protocol:** Простой POST-протокол. Работает с `curl` без прокси. Полная совместимость с gRPC-клиентами. Поддерживает все 4 типа streaming.

## Практические сценарии

### Определение API (.proto файл)

```protobuf
syntax = "proto3";

package order.v1;

import "google/protobuf/timestamp.proto";
import "google/protobuf/empty.proto";

// Сервис заказов
service OrderService {
  // Унарный RPC
  rpc CreateOrder(CreateOrderRequest) returns (CreateOrderResponse);
  // Серверный стриминг
  rpc WatchOrders(WatchRequest) returns (stream OrderEvent);
  // Клиентский стриминг
  rpc UploadReceipts(stream Receipt) returns (UploadSummary);
  // Бидирекшнл стриминг
  rpc OrderChat(stream ChatMessage) returns (stream ChatMessage);
  // Стандартный Health Check
  rpc Check(google.protobuf.Empty) returns (HealthCheckResponse);
}

message CreateOrderRequest {
  string product_id = 1;
  int32 quantity = 2;
  string customer_email = 3;
}

message CreateOrderResponse {
  string order_id = 1;
  google.protobuf.Timestamp created_at = 2;
}

message OrderEvent {
  string order_id = 1;
  string status = 2;  // "created", "paid", "shipped"
  google.protobuf.Timestamp timestamp = 3;
}

message Receipt {
  string order_id = 1;
  bytes image_data = 2;
}

message UploadSummary {
  int32 success_count = 1;
  repeated string failed_ids = 2;
}

message WatchRequest {
  string customer_id = 1;
}

message ChatMessage {
  string text = 1;
}

message HealthCheckResponse {
  string status = 1;  // "SERVING", "NOT_SERVING"
}
```

### Определение API с Protobuf Editions (v25+)

```protobuf
edition = "2023";

package user.v1;

message User {
  string name = 1;
  int32 age = 2 [(opt_targets).field_presence = EXPLICIT];
  string email = 3;
}
```

### Сервер на Go (grpc-go)

```go
package main

import (
    "context"
    "log"
    "net"

    "google.golang.org/grpc"
    "google.golang.org/grpc/codes"
    "google.golang.org/grpc/health"
    healthpb "google.golang.org/grpc/health/grpc_health_v1"
    "google.golang.org/grpc/credentials"
    "google.golang.org/grpc/reflection"
    pb "myproject/proto/order/v1"
)

type orderServer struct {
    pb.UnimplementedOrderServiceServer
}

func (s *orderServer) CreateOrder(ctx context.Context, req *pb.CreateOrderRequest) (*pb.CreateOrderResponse, error) {
    // Проверяем deadline
    if ctx.Err() == context.DeadlineExceeded {
        return nil, grpc.Errorf(codes.DeadlineExceeded, "order creation timeout")
    }

    // Бизнес-логика
    return &pb.CreateOrderResponse{
        OrderId:   "order-123",
        CreatedAt: timestamppb.Now(),
    }, nil
}

func main() {
    // TLS
    creds, err := credentials.NewServerTLSFromFile("server.pem", "server.key")
    if err != nil {
        log.Fatal(err)
    }

    lis, err := net.Listen("tcp", ":50051")
    if err != nil {
        log.Fatal(err)
    }

    // Интерцепторы
    grpcServer := grpc.NewServer(
        grpc.Creds(creds),
        grpc.ChainUnaryInterceptor(
            loggingInterceptor,
            recoveryInterceptor,
        ),
    )

    // Регистрация сервиса
    pb.RegisterOrderServiceServer(grpcServer, &orderServer{})

    // Health Check (нативный gRPC)
    hs := health.NewServer()
    healthpb.RegisterHealthServer(grpcServer, hs)
    hs.SetServingStatus("order.v1.OrderService", healthpb.HealthCheckResponse_SERVING)

    // Reflection для grpcurl
    reflection.Register(grpcServer)

    log.Println("gRPC server listening on :50051")
    grpcServer.Serve(lis)
}

func loggingInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
    log.Printf("Method: %s", info.FullMethod)
    start := time.Now()
    resp, err := handler(ctx, req)
    log.Printf("Method: %s Duration: %v Error: %v", info.FullMethod, time.Since(start), err)
    return resp, err
}
```

### Сервер на Python (grpcio)

```python
import grpc
from concurrent import futures
import order_pb2
import order_pb2_grpc

class OrderServicer(order_pb2_grpc.OrderServiceServicer):
    def CreateOrder(self, request, context):
        # Проверка deadline
        if context.is_active() is False:
            context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "timeout")

        # Бизнес-логика
        return order_pb2.CreateOrderResponse(
            order_id="order-123",
            created_at=timestamp_pb2.Timestamp().GetCurrentTime()
        )

    def WatchOrders(self, request, context):
        # Серверный стриминг
        for event in get_events(request.customer_id):
            yield order_pb2.OrderEvent(
                order_id=event.order_id,
                status=event.status,
                timestamp=event.timestamp
            )

def serve():
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[LoggingInterceptor()]
    )

    order_pb2_grpc.add_OrderServiceServicer_to_server(
        OrderServicer(), server
    )

    # TLS
    with open('server.key', 'rb') as f:
        server_key = f.read()
    with open('server.pem', 'rb') as f:
        server_cert = f.read()

    server.add_secure_port(
        '[::]:50051',
        grpc.ssl_server_credentials([(server_key, server_cert)])
    )

    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
```

### Клиент с retry и deadline

```go
conn, err := grpc.NewClient(
    "dns:///orderservice.default.svc.cluster.local:50051",
    grpc.WithTransportCredentials(insecure.NewCredentials()),
    grpc.WithDefaultServiceConfig(`{
        "methodConfig": [{
            "name": [{"service": "order.v1.OrderService"}],
            "retryPolicy": {
                "maxAttempts": 3,
                "initialBackoff": "0.1s",
                "maxBackoff": "1s",
                "backoffMultiplier": 2,
                "retryableStatusCodes": ["UNAVAILABLE"]
            },
            "timeout": "5s"
        }]
    }`),
)
defer conn.Close()

client := pb.NewOrderServiceClient(conn)

// Timeout для конкретного запроса
ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
defer cancel()

resp, err := client.CreateOrder(ctx, &pb.CreateOrderRequest{
    ProductId:     "prod-123",
    Quantity:      2,
    CustomerEmail: "user@example.com",
})
```

### Интерцепторы

**Go — Unary Interceptor (цепочка):**
```go
func authInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
    md, ok := metadata.FromIncomingContext(ctx)
    if !ok {
        return nil, grpc.Errorf(codes.Unauthenticated, "missing metadata")
    }

    token := md.Get("authorization")
    if len(token) == 0 {
        return nil, grpc.Errorf(codes.Unauthenticated, "missing token")
    }

    // Проверка JWT
    claims, err := validateToken(token[0])
    if err != nil {
        return nil, grpc.Errorf(codes.Unauthenticated, "invalid token")
    }

    // Передаём claims через контекст
    ctx = context.WithValue(ctx, "claims", claims)
    return handler(ctx, req)
}
```

**Python — Interceptor:**
```python
class LoggingInterceptor(grpc.UnaryServerInterceptor):
    def intercept_service(self, continuation, handler_call_details):
        method = handler_call_details.method
        start = time.time()

        def wrapper(request):
            response = continuation(handler_call_details)(request)
            duration = time.time() - start
            print(f"Method: {method}, Duration: {duration:.3f}s")
            return response

        return grpc.unary_unary_rpc_method_handler(wrapper)
```

### Балансировка нагрузки

Стандартная балансировка L4 (на уровне TCP-соединений) для gRPC неэффективна, так как соединения долгоживущие.
**Современные подходы:**
*   **Client-side Load Balancing:** Клиент получает список IP-адресов бэкендов и сам распределяет запросы (например, через библиотеку `grpc-go` с DNS-резолвером).
*   **L7 Proxy (Envoy/Nginx/Angie):** Прокси-сервер терминирует gRPC-потоки и балансирует их по отдельности между бэкендами.
*   **Kubernetes Gateway API:** Использование ресурса `GRPCRoute` (GA в v1.1) для маршрутизации трафика на основе имен методов и сервисов.
*   **xDS API:** Динамическая конфигурация балансировки через Envoy xDS (CDS, EDS, LDS, RDS). Поддерживается grpc-go через `xds` resolver.
*   **Lookaside Load Balancing:** Клиент запрашивает актуальную информацию о нагрузке у control plane (LRS — Load Reporting Service).

### Обработка ошибок

gRPC использует собственные статус-коды (17 стандартных значений):

| Код | Имя | Описание | Пример использования |
| :--- | :--- | :--- | :--- |
| 0 | OK | Успех | — |
| 1 | CANCELLED | Запрос отменён клиентом | `context.WithCancel()` |
| 2 | UNKNOWN | Неизвестная ошибка | Исключения без специфичного кода |
| 3 | INVALID_ARGUMENT | Невалидный аргумент | Неправильный формат email |
| 4 | DEADLINE_EXCEEDED | Таймаут | Превышен `ctx.WithTimeout()` |
| 5 | NOT_FOUND | Ресурс не найден | Заказ не существует |
| 6 | ALREADY_EXISTS | Ресурс уже существует | Дубликат заказа |
| 7 | PERMISSION_DENIED | Нет прав | Недостаточно привилегий |
| 8 | RESOURCE_EXCEEDED | Исчерпаны ресурсы | Лимит API |
| 9 | FAILED_PRECONDITION | Предусловие не выполнено | Попытка удалить непустую папку |
| 10 | ABORTED | Операция прервана | Конфликт оптимистичной блокировки |
| 11 | OUT_OF_RANGE | Вне диапазона | Индекс за пределами массива |
| 12 | UNIMPLEMENTED | Не реализовано | Метод не поддерживается |
| 13 | INTERNAL | Внутренняя ошибка сервера | Баг в коде |
| 14 | UNAVAILABLE | Сервер недоступен | Перезагрузка, health check failed |
| 15 | DATA_LOSS | Потеря данных | Невосстанавливаемая потеря |
| 16 | UNAUTHENTICATED | Не аутентифицирован | Невалидный/отсутствующий JWT |

Для передачи расширенной информации об ошибках используется объект `google.rpc.Status`, позволяющий упаковать дополнительные Protobuf-сообщения (например, `RetryInfo`, `BadRequest`, `ErrorInfo`) в поле `details`.

### TLS и mTLS

```go
// Сервер с mTLS
creds, err := credentials.NewServerTLSFromFile("server.pem", "server.key")

// Клиент с mTLS
cert, err := tls.LoadX509KeyPair("client.pem", "client.key")
caCert, err := os.ReadFile("ca.pem")
caPool := x509.NewCertPool()
caPool.AppendCertsFromPEM(caCert)

tlsConfig := &tls.Config{
    Certificates: []tls.Certificate{cert},
    RootCAs:      caPool,
}
creds := credentials.NewTLS(tlsConfig)

conn, err := grpc.NewClient("orderservice:50051", grpc.WithTransportCredentials(creds))
```

### Health Check (gRPC Health Protocol)

Стандартный протокол `grpc.health.v1.Health`:

```go
// На сервере
hs := health.NewServer()
healthpb.RegisterHealthServer(grpcServer, hs)

// Установка статуса для конкретного сервиса
hs.SetServingStatus("order.v1.OrderService", healthpb.HealthCheckResponse_SERVING)

// Проверка извне (grpc-health-probe)
// $ grpc-health-probe -addr=localhost:50051 -service=order.v1.OrderService
```

```yaml
# Kubernetes Probe
livenessProbe:
  exec:
    command: ["/grpc-health-probe", "-addr=:50051"]
readinessProbe:
  exec:
    command: ["/grpc-health-probe", "-addr=:50051", "-service=order.v1.OrderService"]
```

### Инструментарий и экосистема

*   **[Buf](https://buf.build/):** Современная замена стандартному `protoc`. Включает в себя линтинг, проверку обратной совместимости (breaking changes), генерацию кода и централизованный реестр схем.
*   **grpcurl / gRPCui:** CLI и Web-интерфейсы для взаимодействия с gRPC-серверами без написания кода.
*   **grpc-health-probe:** Утилита для проверки здоровья контейнеров в средах без нативной поддержки gRPC-проб.
*   **Envoy:** L7-прокси с нативной поддержкой gRPC, HTTP/2, клиентской балансировкой и可观測ность.
*   **OpenTelemetry:** Стандартный сбор метрик (latency, throughput, error rate) и трейсинг gRPC-вызовов через interceptors.
*   **gRPCurl с reflection:**
    ```bash
    # Просмотр доступных сервисов
    grpcurl -plaintext localhost:50051 list

    # Вызов метода
    grpcurl -d '{"product_id": "prod-123", "quantity": 2}' \
      -plaintext localhost:50051 order.v1.OrderService/CreateOrder
    ```

### Connect RPC (_BUF_BUILD_)

```go
// Сервер (connect-go)
import (
    "connectrpc.com/connect"
    "context"
)

type OrderHandler struct{}

func (h *OrderHandler) CreateOrder(
    ctx context.Context,
    req *connect.Request[pb.CreateOrderRequest],
) (*connect.Response[pb.CreateOrderResponse], error) {
    // Та же бизнес-логика, что и в gRPC
    return connect.NewResponse(&pb.CreateOrderResponse{
        OrderId: "order-123",
    }), nil
}

func main() {
    mux := http.NewServeMux()
    path, handler := connect.NewOrderServiceHandler(&OrderHandler{})
    mux.Handle(path, handler)

    // Supports gRPC, gRPC-Web, AND Connect protocols automatically
    log.Fatal(http.ListenAndServeTLS(":8443", "cert.pem", "key.pem", mux))
}
```

```bash
# Вызов через curl (Connect protocol)
curl -X POST https://localhost:8443/order.v1.OrderService/CreateOrder \
  -H "Content-Type: application/json" \
  -d '{"productId": "prod-123", "quantity": 2}'

# Вызов через grpcurl (gRPC protocol)
grpcurl -d '{"product_id": "prod-123", "quantity": 2}' \
  -plaintext localhost:8443 order.v1.OrderService/CreateOrder
```

### Мониторинг и Observability

```go
import "go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"

// Сервер
grpcServer := grpc.NewServer(
    grpc.StatsHandler(otelgrpc.NewServerHandler()),
)

// Клиент
conn, err := grpc.NewClient("orderservice:50051",
    grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
    grpc.WithTransportCredentials(insecure.NewCredentials()),
)
```

```yaml
# Prometheus метрики (экспортируются через OpenTelemetry)
# grpc_server_handled_total{grpc_type="unary",grpc_service="order.v1.OrderService",grpc_method="CreateOrder"}
# grpc_server_handling_seconds_bucket{grpc_type="unary",...}
# grpc_client_handled_total{grpc_code="OK",...}
```

## Дополнительная информация

### Безопасность
*   **TLS/mTLS:** Основной механизм защиты. mTLS (взаимный TLS) обеспечивает аутентификацию обеих сторон через сертификаты. Post-Quantum TLS (ML-KEM) по умолчанию в gRPC 1.83+.
*   **Token-based Auth:** Передача токенов (JWT) через метаданные запроса.
*   **RBAC:** Аутентификация и авторизация через Envoy/Service Mesh (Istio, Linkerd).

### Сравнение с альтернативами

| Параметр | gRPC | REST (JSON) | GraphQL | Connect |
| :--- | :--- | :--- | :--- | :--- |
| **Сериализация** | Бинарная (Protobuf) | Текстовая (JSON) | Текстовая (JSON) | Бинарная/JSON |
| **Контракт** | Строгий (.proto) | Опциональный (OpenAPI) | Строгий (Schema) | Строгий (.proto) |
| **Стриминг** | Нативный (4 типа) | Ограничен (SSE/Long polling) | Subscriptions | Нативный (4 типа) |
| **HTTP версия** | HTTP/2, HTTP/3 | HTTP/1.1, 2, 3 | HTTP/1.1, 2 | HTTP/1.1, 2, 3 |
| **Браузерная поддержка** | Нет (нужен Envoy) | Да | Да | Да (нужен прокси) |
| **curl-совместимость** | Нет | Да | Да | Да |
| **Мультиплексирование** | Стримовое | Нет | Нет | Стримовое |

### Типичные ошибки и решения

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **HOL Blocking** | Латентность растёт из-за одного медленного стрима | Использовать HTTP/3 (QUIC) или несколько TCP-соединений |
| **L4 балансировка** | Неравномерная нагрузка на бэкенды | Перейти на L7-прокси (Envoy) или client-side balancing |
| **Пропажа Deadline** | Timeout на промежуточном сервисе, хотя клиент ждёт | Пропагировать deadline через `grpc-timeout` заголовки |
| **Retry Storm** | Массовые повторные запросы при падении сервера | Ограничить retry: maxAttempts, maxBackoff, chỉ retry на UNAVAILABLE |
| **gRPC за прокси** | Ошибка "HTTP/2 required" | Включить HTTP/2 в прокси или использовать Connect/gRPC-Web |
| **Reflection не работает** | grpcurl не находит сервисы | Убедиться что `reflection.Register(grpcServer)` вызван после `Register*Server` |

### См. также

*   **[CDN — WebSocket, SSE и gRPC](../CDN/cdn_websocket_sse_grpc.md)** — проксирование gRPC через CDN (Cloudflare, Nginx).
*   **[Оптимизация HTTP-протоколов](../Protocols/HTTP/http_protocols_optimization.md)** — глубокий разбор HTTP/2 и HTTP/3.
*   **[Прикладной уровень OSI](../OSI_TCP_IP_Model/application_layer.md)** — роль gRPC в стеке протоколов.
*   **[Уровень представления OSI](../OSI_TCP_IP_Model/presentation_layer.md)** — сериализация данных и форматы.
*   **[Протокол OTLP](../../OpenTelemetry/otlp_protocol.md)** — использование gRPC для передачи телеметрии.
*   **[Проверки здоровья в Kubernetes](../../Kubernetes/Base/probes.md)** — нативная поддержка gRPC-проб.
*   **[Consul Health Checks](../../Consul/consul_health_checks.md)** — gRPC health check в Consul.
*   **[Service Mesh: Envoy Sidecar](../../Service_Mesh/proxy_sidecar.md)** — gRPC балансировка через Envoy.
*   **[Кэширование: Protobuf](../../Concepts/Caching/caching_overview.md)** — Protobuf в контексте кэширования.
