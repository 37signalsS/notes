#### 6. Запуск и проверка тестового приложения

##### 6.1. Сборка и отправка Docker-образа

```bash
cd opentelemetry-java-examples/agent/agent-example-app
./gradlew clean bootJar
docker build -t registry.test:30000/agent-example-app:latest .
docker push registry.test:30000/agent-example-app:latest
```

##### 6.2. Запуск приложения с автоматической инструментацией

Аннотация `instrumentation.opentelemetry.io/inject: "true"` указывает оператору внедрить OTel-агент.

```bash
kubectl run agent-example-app 
  --image=registry.test:30000/agent-example-app:latest 
  --port=8080 
  --labels="app=agent-example-app" 
  --annotations='instrumentation.opentelemetry.io/inject: "true"' 
  --namespace=default
```

##### 6.3. Проверка телеметрии

1. **Проброс порта**:

    ```bash
    kubectl port-forward pod/$(kubectl get pods -l app=agent-example-app -o jsonpath='{.items[0].metadata.name}') 8080:8080
    ```

2. **Генерация нагрузки**:

    ```bash
    curl localhost:8080/ping
    ```

3. **Просмотр в Grafana**: Откройте Grafana (<http://grafana.test>) и перейдите в раздел Explore.
    - **Логи**: Выберите Data Source `Loki`, используйте запрос `{service_name="agent-example-app"}`. Вы увидите логи приложения.
    - **Трассировки**: В логах найдите `traceID` и перейдите по нему в Tempo. Вы увидите полную трассировку запроса.
    - **Метрики**: Выберите Data Source `Prometheus`, используйте запрос `traces_spanmetrics_latency_bucket{service_name="agent-example-app"}`. Вы увидите метрики, сгенерированные из спанов.

### Альтернативный сценарий: запуск с Java Agent вручную

Этот способ демонстрирует запуск приложения с Java Agent напрямую, без использования OpenTelemetry Operator.

1. **Сборка образа (без встроенного агента)**:
    Убедитесь, что Dockerfile не содержит инструкций по копированию и активации `opentelemetry-javaagent.jar`.

    ```bash
    cd opentelemetry-java-examples/agent/agent-example-app
    docker build -t registry.test:30000/agent-example-app-no-agent:latest .

docker push registry.test:30000/agent-example-app-no-agent:latest
    ```
2.  **Запуск пода с явным указанием агента**:
    Этот метод требует, чтобы JAR-файл агента был доступен в контейнере (например, через `initContainer` или путем встраивания в образ).
    ```bash
    kubectl run agent-example-app-manual 
      --image=registry.test:30000/agent-example-app-no-agent:latest 
      --port=8080 
      --labels="app=agent-example-app-manual" 
      --env="JAVA_TOOL_OPTIONS=-javaagent:/path/to/opentelemetry-javaagent.jar" 
      --env="OTEL_EXPORTER_OTLP_ENDPOINT=<http://default.opentelemetry:4317>" 
      --env="OTEL_LOGS_EXPORTER=otlp" 
      --env="OTEL_SERVICE_NAME=agent-example-app-manual"
    ```