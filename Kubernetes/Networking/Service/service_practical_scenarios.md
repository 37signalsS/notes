# Service Practical Scenarios

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация полного цикла от внутреннего сервиса (ClusterIP) до внешнего доступа (NodePort).

**Предварительные требования:**
- Работающий кластер Kubernetes
- Развёрнутый `Deployment` с именем `nginx-deployment`, управляющий подами с меткой `app: nginx`

## Основные концепции

### Последовательность публикации

Рекомендуемый подход к публикации приложений:

1. **ClusterIP** — внутренний доступ для тестирования и отладки
2. **NodePort** — внешний доступ для разработки и on-premise сред
3. **LoadBalancer/Ingress** — production-публикация (см. [соответствующие документы](./service_types_summary.md))

### Принципы

| Принцип | Описание |
| :--- | :--- |
| **Gradual exposure** | Постепенное открытие доступа: от внутреннего к внешнему |
| **Селекторы** | Service выбирает поды через `selector`, должен совпадать с метками подов |
| **Namespace** | Pod и Service должны быть в одном namespace для прямого взаимодействия |
| **Порты** | `port` — порт сервиса, `targetPort` — порт приложения, `nodePort` — внешний порт |

## Практические сценарии

### Сценарий 1: Публикация через ClusterIP (внутренний доступ)

Создадим сервис типа **[ClusterIP](./service_type_clusterip.md)** для внутреннего доступа к Nginx.

#### Манифест Service

```yaml
# nginx-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  # Селектор должен совпадать с метками подов Deployment
  selector:
    app: nginx

  # type: ClusterIP можно не указывать (значение по умолчанию)
  type: ClusterIP

  ports:
    - name: http
      protocol: TCP
      # port: порт сервиса внутри кластера
      port: 8080
      # targetPort: порт на подах, куда перенаправляется трафик
      targetPort: 80
```

#### Создание и проверка

**1. Применяем манифест:**

```bash
kubectl apply -f nginx-service.yaml
# service/nginx-service created
```

**2. Проверяем сервис:**

```bash
kubectl get service nginx-service
# NAME            TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)    AGE
# nginx-service   ClusterIP   10.104.117.48   <none>        8080/TCP   30s
```

Сервису присвоен внутренний IP `10.104.117.48`.

**3. Проверка доступа (изнутри кластера):**

```bash
# Запрос на виртуальный IP сервиса
curl 10.104.117.48:8080
```

Ожидаемый результат: стандартная приветственная страница Nginx. `kube-proxy` перехватит запрос и сбалансирует его на один из подов `nginx-deployment`.

---

### Сценарий 2: Преобразование в NodePort (внешний доступ)

Изменим тип сервиса на **[NodePort](./service_type_nodeport.md)** для внешнего доступа.

#### Изменение манифеста

```yaml
# nginx-service.yaml (обновлённая версия)
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  selector:
    app: nginx

  # Меняем тип сервиса
  type: NodePort

  ports:
    - name: http
      protocol: TCP
      port: 8080
      targetPort: 80
      # Указываем конкретный NodePort (опционально)
      # Если не указать, будет выбран случайный порт из 30000-32767
      nodePort: 30080
```

#### Обновление и проверка

**1. Применяем изменённый манифест:**

```bash
kubectl apply -f nginx-service.yaml
# service/nginx-service configured
```

**2. Проверяем сервис:**

```bash
kubectl get service nginx-service
# NAME            TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)          AGE
# nginx-service   NodePort   10.104.117.48   <none>        8080:30080/TCP   5m
```

**Изменения:**
- Тип: `ClusterIP` → `NodePort`
- `CLUSTER-IP` сохранён
- `PORT(S)`: `8080:30080` — порт `30080` открыт на всех узлах

**3. Проверка доступа (снаружи кластера):**

```bash
# IP-адреса нод: 192.168.1.10, 192.168.1.11, 192.168.1.12

# Запрос на любую ноду кластера
curl http://192.168.1.10:30080
curl http://192.168.1.11:30080
curl http://192.168.1.12:30080
```

Каждый запрос вернёт страницу Nginx. `NodePort` открывает порт на всех узлах и перенаправляет трафик на поды независимо от их расположения.

## Дополнительная информация

### Диагностика и troubleshooting

| Команда | Описание |
| :--- | :--- |
| `kubectl get svc` | Список всех сервисов |
| `kubectl describe svc <name>` | Детальная информация о сервисе |
| `kubectl get endpoints <name>` | Проверка IP подов за сервисом |
| `kubectl logs <pod-name>` | Логи пода для отладки |

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` | Поды не готовы | `kubectl get pods`, проверка readiness probe |
| `No endpoints` | Селектор не совпадает | Проверить метки подов: `kubectl get pods --show-labels` |
| Доступ только с одной ноды | Поды на других нодах не готовы | Проверить статус подов и CNI-плагин |

### Альтернативные сценарии

- **LoadBalancer:** Для production в облаке см. [LoadBalancer](./service_type_loadbalancer.md)
- **Ingress:** Для HTTP/HTTPS маршрутизации см. [Ingress](../Ingress/overview.md)
- **ExternalIPs:** Для статических внешних IP (депрецируется v1.36) см. [ExternalIPs](./service_externalips.md)
