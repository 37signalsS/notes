# Методы доступа к GitLab в Kubernetes

Руководство по настройке доступа к веб-интерфейсу GitLab при развертывании в кластерах Kubernetes через различные типы сервисов и контроллеров.

---

## Определения

| Термин | Описание |
|--------|----------|
| **LoadBalancer** | Тип сервиса, создающий внешний балансировщик нагрузки. В облаках (AWS, GCP) создается автоматически, в Bare-Metal требует MetalLB. |
| **NodePort** | Тип сервиса, открывающий статический порт на каждом узле кластера для внешнего доступа. |
| **Ingress** | Ресурс Kubernetes, управляющий внешним доступом к сервисам (обычно HTTP/HTTPS) с функциями маршрутизации и терминации SSL. |
| **ExternalIPs** | Параметр сервиса, позволяющий перенаправлять трафик, приходящий на конкретный IP узла, в Service. |

---

## Основные концепции

### Выбор метода доступа

Выбор метода зависит от инфраструктуры, на которой развернут кластер:

1. **Облачные провайдеры**: Рекомендуется `LoadBalancer`. Чарт GitLab по умолчанию настроен на использование встроенного NGINX Ingress с типом сервиса `LoadBalancer`.
2. **Bare-Metal (Production)**: Рекомендуется сочетание `MetalLB` (для реализации `LoadBalancer`) и `Ingress`.
3. **Bare-Metal (Dev/Test)**: Допускается использование `NodePort` или `ExternalIPs` для упрощения конфигурации без внешних балансировщиков.

### Взаимодействие компонентов

В стандартной установке Helm-чарта трафик проходит следующий путь:
`Клиент → (LoadBalancer/NodePort) → NGINX Ingress Controller → GitLab Webservice`.

---

## Практические сценарии

### Настройка LoadBalancer в Bare-Metal

По умолчанию сервис типа `LoadBalancer` остается в состоянии `<pending>` в кластерах без облачного провайдера.

**Варианты реализации:**

- **MetalLB**: Установите и настройте [MetalLB](../Networking/metallb.md). После этого сервис Ingress получит внешний IP автоматически.
- **Прямое указание IP (ExternalIPs)**: Если MetalLB не используется, можно привязать сервис к конкретному IP-адресу узла.

**Пример установки с привязкой к IP узла:**

```bash
# Определение IP узла
kubectl get nodes -o wide

# Установка с указанием externalIP
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set nginx-ingress.controller.service.externalIPs={192.168.1.50}
```

### Использование NodePort для доступа

Метод полезен, когда Ingress-контроллер не может получить внешний IP или если необходимо обойти Ingress.

**Настройка через переопределение параметров:**

```bash
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  --timeout 600s \
  --set global.hosts.domain=example.com \
  --set nginx-ingress.enabled=false \
  --set gitlab.webservice.service.type=NodePort
```

**Проверка назначенных портов:**

```bash
# Получение внешнего порта (диапазон 30000-32767)
kubectl get svc -n gitlab gitlab-webservice -o jsonpath='{.spec.ports[0].nodePort}'
```

**Доступ:** `http://<NODE_IP>:<NODE_PORT>`

### Доступ через внешний Ingress-контроллер

Если в кластере уже установлен Ingress (например, ingress-nginx), встроенный контроллер чарта следует отключить.

```yaml
# values.yaml
global:
  ingress:
    enabled: true
    configureCertmanager: false
nginx-ingress:
  enabled: false
```

---

## Дополнительная информация

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Типы сервисов Kubernetes](../Networking/Service/service_types_summary.md)
- [Настройка MetalLB](../Networking/metallb.md)
