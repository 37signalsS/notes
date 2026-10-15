# Crossplane: Разработка кастомных Composition Functions

**Актуально для:** Crossplane v1.17+ / v2.x (актуально v2.4); function-sdk-go v0.6+ / v0.7+; function-sdk-python; Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

## Определения

**Composition Function (кастомная)** — самостоятельно разработанный OCI-пакет (`kind: Function`, API-группа `pkg.crossplane.io`), реализующий произвольную логику генерации ресурсов поверх gRPC-протокола Crossplane. Отличается от готовых функций (`function-patch-and-transform`, `function-go-templating`) наличием собственного кода на Go или Python.

**function-sdk-go** — официальный Go-SDK (`github.com/crossplane/function-sdk-go`), предоставляющий сервер gRPC, типизированные обёртки `RunFunctionRequest` / `RunFunctionResponse`, журналирование и хелперы (`response.Fatal`, `response.Normal`, `resource.Composite`).

**function-sdk-python** — официальный Python-SDK (`crossplane-function-sdk-python`), базовый класс `Runtime` с методом `Run(request) -> RunFunctionResponse`.

**function-template-go** — шаблонный репозиторий для инициализации новой функции (`crossplane xpkg init function-<name> -template-go`), содержащий заготовку Dockerfile, `package/crossplane.yaml`, схему входа и CI.

**Development Runtime** — режим отладки, при котором `crossplane render` направляет gRPC-вызовы напрямую в локально запущенный процесс функции (по `render.crossplane.io/runtime: Development`), без сборки Docker-образа.

**functionConfig (Input)** — YAML-вход шага конвейера, схема которого генерируется из протобуфа/типов SDK и валидируется Crossplane при установке функции.

## Базовые концепции и архитектура

### Контракт gRPC

Каждая функция реализует сервис `FunctionRunnerService` с единственным методом `RunFunction`:

```text
Crossplane Core (FunctionComposer)
      │  gRPC: RunFunctionRequest
      │    • meta (tag, ttl)
      │    • observed (XR, composed resources, extra resources)
      │    • desired (накопленный Desired State предыдущих шагов)
      │    • context (разделяемая шина protobuf.Struct)
      │    • input (functionConfig, специфичный для функции)
      ▼
Function Pod (ваш код)
      │  обработка: паттерны, бизнес-логика, валидация
      ▼
RunFunctionResponse
      • desired (пополненный набор ресурсов)
      • conditions (Ready/Synced для XR)
      • results (Normal/Fatal — события для XR)
      • context (обновлённая шина для следующего шага)
```

Ограничения контракта:

* `MaxRequirementsIterations = 5` — максимум 5 повторных вызовов `RunFunction` при запросе дополнительных ресурсов (`requiredResources`).
* TTL кэширования ответа (по умолчанию 1 минута) управляется через `response.To(req, ttl)`.
* Fatal-результат не может таргетить Claim — только XR.

### Структура проекта кастомной функции (Go)

```text
function-ipam-allocator/
├── cmd/main.go              # точка входа: Serve(fn)
├── fn.go                    # реализация RunFunction
├── input/v1beta1/           # схема functionConfig (генерируется из Go-типов)
│   ├── types.go
│   └── zz_generated.deepcopy.go
├── package/crossplane.yaml  # метаданные OCI-пакета
├── Dockerfile               # distroless + бинарник
└── go.mod
```

## Практические сценарии и конфигурация

### Сценарий 1: Минимальная функция на Go (function-sdk-go)

`fn.go` — обогащение XR значением из внешнего «IPAM» (по сути — бизнес-логика, недоступная патчам):

```go
package main

import (
    "context"
    "fmt"

    "github.com/crossplane/function-sdk-go/errors"
    "github.com/crossplane/function-sdk-go/logging"
    fnv1 "github.com/crossplane/function-sdk-go/proto/v1"
    "github.com/crossplane/function-sdk-go/request"
    "github.com/crossplane/function-sdk-go/resource"
    "github.com/crossplane/function-sdk-go/response"
)

type Function struct {
    fnv1.UnimplementedFunctionRunnerServiceServer
    log logging.Logger
}

func (f *Function) RunFunction(ctx context.Context, req *fnv1.RunFunctionRequest) (*fnv1.RunFunctionResponse, error) {
    rsp := response.To(req, response.DefaultTTL)

    // 1. Чтение XR из запроса
    xr, err := request.GetObservedCompositeResource(req)
    if err != nil {
        response.Fatal(rsp, errors.Wrap(err, "cannot get XR"))
        return rsp, nil
    }

    // 2. Пример бизнес-логики: детерминированный IP из имени XR
    //    (в реальной функции — запрос к внутреннему IPAM/CMDB API)
    ip, err := allocateIP(xr.GetResource().GetName())
    if err != nil {
        response.Fatal(rsp, errors.Wrap(err, "cannot allocate IP"))
        return rsp, nil
    }

    // 3. Запись результата в context — доступно следующим шагам конвейера
    if err := response.SetContextKey(rsp, "corp.internal/allocated-ip", ip); err != nil {
        response.Fatal(rsp, errors.Wrap(err, "cannot set context"))
        return rsp, nil
    }

    // 4. Обогащение status XR (проброс потребителю)
    xr.GetResource().Object["status"] = map[string]interface{}{
        "allocatedIP": ip,
    }
    if err := response.SetDesiredCompositeResource(rsp, xr); err != nil {
        response.Fatal(rsp, errors.Wrap(err, "cannot set desired XR"))
        return rsp, nil
    }

    response.Normal(rsp, fmt.Sprintf("allocated IP %s", ip))
    return rsp, nil
}

func allocateIP(name string) (string, error) {
    // Заглушка: в проде — HTTP/gRPC вызов внутреннего IPAM
    return fmt.Sprintf("10.42.%d.%d", len(name)%250, len(name)%250), nil
}
```

`cmd/main.go`:

```go
package main

import (
    "github.com/crossplane/function-sdk-go/logging"
    "github.com/crossplane/function-sdk-go"
)

func main() {
    log, err := logging.NewLogger(true) // debug mode
    if err != nil {
        panic(err)
    }
    fn := &Function{log: log}
    // Serve запускает gRPC-сервер на :9443
    if err := function.Serve(fn); err != nil {
        log.Info("cannot serve function", "error", err)
    }
}
```

### Сценарий 2: Минимальная функция на Python (function-sdk-python)

```python
from crossplane.function.runtime import Runtime
from crossplane.function.request import RunFunctionRequest
from crossplane.function.response import RunFunctionResponse, Fatal, Normal
from crossplane.function.proto.v1 import response as response_pb2

class MyIPAMFunction(Runtime):
    def Run(self, request: RunFunctionRequest) -> RunFunctionResponse:
        xr = request.observed.composite.resource

        # Бизнес-логика: запрос к внутреннему IPAM
        ip = self._allocate(xr.metadata.name)

        # Обогащение status XR
        xr.object.setdefault("status", {})["allocatedIP"] = ip

        rsp = request.to()
        rsp.desired.composite.resource.CopyFrom(xr)
        rsp.conditions.append(
            response_pb2.Condition(
                type="Ready",
                status="STATUS_CONDITION_TRUE",
                reason="Success",
                target="TARGET_COMPOSITE",
            )
        )
        return rsp

    def _allocate(self, name: str) -> str:
        return f"10.43.{len(name) % 250}.{len(name) % 250}"
```

Точка входа:

```python
from crossplane.function.runtime import serve

if __name__ == "__main__":
    serve(MyIPAMFunction(), address=":9443", insecure=True)
```

### Сценарий 3: Инициализация и сборка через Crossplane CLI

```bash
# 1. Генерация каркаса из шаблона function-template-go
crossplane xpkg init function-ipam-allocator \
  -template-go \
  -d function-ipam-allocator
# → Initialized package "function-ipam-allocator" from
#   https://github.com/crossplane/function-template-go

# 2. Переход в каталог и запуск скрипта инициализации зависимостей
cd function-ipam-allocator
./init.sh

# 3. Определение схемы входа (input/v1beta1/types.go):
#    type Input struct {
#        IPAMPEndpoint string `json:"ipamEndpoint"`
#        CIDR          string `json:"cidr"`
#    }
#    затем:
go generate ./...

# 4. Локальная отладка (Development Runtime — см. testing_crossplane.md)
go run ./cmd/main.go --address localhost:9443 --insecure

# 5. Сборка OCI-пакета
crossplane xpkg build --package-root=. -o function-ipam-allocator.xpkg

# 6. Публикация в корпоративный Harbor
crossplane xpkg push \
  --package-files=function-ipam-allocator.xpkg \
  harbor.internal.corp/crossplane/function-ipam-allocator:v0.1.0
```

### Сценарий 4: Установка и подключение к конвейеру

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-ipam-allocator
spec:
  package: harbor.internal.corp/crossplane/function-ipam-allocator:v0.1.0
  packagePullSecrets:
    - name: harbor-creds
```

```bash
kubectl apply -f function.yaml
kubectl get function function-ipam-allocator
# → NAME                      INSTALLED   HEALTHY   PACKAGE
# → function-ipam-allocator   True        True      harbor.../function-ipam-allocator:v0.1.0
```

Использование в Composition:

```yaml
pipeline:
  - step: allocate-ip
    functionRef:
      name: function-ipam-allocator
    input:
      apiVersion: ipam.platform.internal/v1beta1
      kind: Input
      ipamEndpoint: "https://ipam.corp.internal/api"
      cidr: "10.42.0.0/16"
  - step: patch-and-transform
    functionRef:
      name: function-patch-and-transform
    input:
      apiVersion: pt.fn.crossplane.io/v1beta1
      kind: Resources
      resources:
        - name: network-interface
          # ... читает context["corp.internal/allocated-ip"] через
          #     function-environment-configs / ToEnvironmentFieldPath
```

## Операции и команды

| Задача | Команда |
|---|---|
| Инициализация каркаса (Go) | `crossplane xpkg init function-<name> -template-go -d <dir>` |
| Сборка пакета | `crossplane xpkg build --package-root=. -o fn.xpkg` |
| Публикация | `crossplane xpkg push --package-files=fn.xpkg <registry>/<repo>:<tag>` |
| Статус установленной функции | `kubectl get function` / `kubectl get functionrevisions` |
| Локальный рендер с Development Runtime | `crossplane render xr.yaml composition.yaml functions.yaml` (с аннотацией `render.crossplane.io/runtime: Development`) |
| Логи пода функции | `kubectl logs -n crossplane-system -l pkg.crossplane.io/pkg=function-<name> --tail=100` |
| Проверка gRPC-порта | `kubectl exec -n crossplane-system deploy/crossplane -- nc -zvw3 function-<name> 9443` |

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `function ... is not ready` / `PackagePullBackOff` | OCI-образ недоступен, неверный тег или нет `packagePullSecrets` | `kubectl describe function <name>` | Исправить референс пакета, добавить секрет реестра |
| `cannot get Function input` | Схема `input` в Composition не совпадает с типами SDK (`go generate` не запущен) | Логи функции + `kubectl get crd \| grep <fn>` | Перегенерировать deepcopy, пересобрать xpkg |
| `context deadline exceeded` (15s) | Функция зависла на внешнем вызове (IPAM/CMDB) | Таймаут в логах Crossplane Core | Добавить таймауты и ретраи в коде; при необходимости увеличить `--function-runner-timeout` |
| Ресурсы не появляются в Desired State | Функция не вызывает `SetDesiredResources` / не копирует observed → desired | `crossplane render ... --include-context` | Проверить, что Desired State пополняется (в Go — `response.SetDesiredResources` / `SetDesiredComposedResources`) |
| `unknown field` при установке | В `package/crossplane.yaml` отсутствует мета-схема или неверный `spec.crossplane` | `kubectl describe functionrevision` | Сверить `package/crossplane.yaml` с шаблоном; проверить совместимость SDK с версией Core |
| CI/CD падает на `xpkg build` | Отсутствует Dockerfile или бинарник не скопирован в образ | Вывод `crossplane xpkg build` | Проверить multi-stage Dockerfile (go build → distroless) |

## Лучшие практики (Best Practices)

1. **Начинайте с шаблона (`-template-go`), а не с нуля** — он гарантирует совместимость схемы input и Dockerfile с текущей версией Core.
2. **Идемпотентность обязательна:** `RunFunction` вызывается на каждом reconcile; внешние вызовы (IPAM, CMDB) оборачивайте в кэш/TTL или используйте `response.To(req, ttl)` для кэширования ответа.
3. **Fatal только для невосстановимых ошибок** (нет обязательного параметра, недоступна внешняя система). Штатные состояния («ресурс ещё не создан») — через `conditions` / `results.Normal`.
4. **Отладка — через Development Runtime** (см. [Тестирование платформы](./testing_crossplane.md)), сборка Docker-образа только перед коммитом.
5. **Тестируйте функцию golden-тестами** через `crossplane render` в CI: фиксируйте эталонный вывод и сравнивайте.
6. **Не дублируйте готовые функции.** Если логика — это патчи/условия, используйте `function-patch-and-transform` / `function-go-templating` / `function-kcl`; кастомная функция оправдана только при интеграции с внешними системами или уникальной бизнес-логикой.
7. **Версионируйте OCI-пакеты по semver и фиксируйте по digest** в прод-кластерах (см. [Безопасность пакетов](./package_security.md)).

## Дополнительная информация

### Внутренние ссылки

* [Composition Functions и EnvironmentConfig](./composition_functions.md) — общий контракт gRPC и экосистема функций.
* [Тестирование платформы](./testing_crossplane.md) — Development Runtime, golden-тесты, CI.
* [Патчи, трансформы и PatchSets](./patch_transform.md) — когда кастомная функция не нужна.
* [Безопасность пакетов](./package_security.md) — подпись и проверка OCI-пакетов функций.

### Внешние ресурсы

* [Write a Composition Function in Go (Crossplane v2.4)](https://docs.crossplane.io/v2.4/guides/write-a-composition-function-in-go/) — официальный гайд.
* [crossplane/function-sdk-go](https://github.com/crossplane/function-sdk-go) — Go-SDK, API `response`, `request`, `resource`.
* [crossplane/function-sdk-python](https://crossplane.github.io/function-sdk-python/) — Python-SDK, базовый класс `Runtime`.
* [crossplane/function-template-go](https://github.com/crossplane/function-template-go) — шаблон для `xpkg init`.
