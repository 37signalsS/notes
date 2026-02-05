# Установка Grafana в Kubernetes с использованием Helm

Этот документ описывает установку и конфигурацию Grafana в кластере Kubernetes с использованием Helm.

## 1. Определения

- **Helm-чарт Grafana** — это пакет преднастроенных ресурсов Kubernetes, который автоматизирует установку, обновление и управление Grafana в кластере.
- **`values.yaml`** — файл конфигурации, используемый для кастомизации Helm-чарта перед установкой.

## 2. Основные концепции

Для эффективной установки Grafana с помощью Helm важно понимать следующие концепции:

- **Персистентность (Persistence)**: Обеспечивает сохранение данных Grafana (дашборды, источники данных, настройки) между перезапусками подов. Для этого используется PersistentVolumeClaim (PVC), что критически важно для продуктивных сред, чтобы избежать потери данных при сбоях или обновлениях.

- **Внешний доступ (Ingress)**: Ресурс Kubernetes, который настраивает правила для предоставления доступа к веб-интерфейсу Grafana извне кластера через контроллер (например, Nginx).

- **`root_url`**: Ключевой параметр конфигурации в `grafana.ini`, определяющий публичный URL-адрес Grafana. Он используется для генерации корректных ссылок в уведомлениях, приглашениях и других компонентах интерфейса. Неправильная настройка этого параметра — частая причина ошибок.

- **Provisioning**: Механизм автоматической загрузки и настройки ресурсов (дашбордов, источников данных) при старте Grafana. В Helm-чарте это часто реализуется через **`sidecar`**, который отслеживает ConfigMaps с определениями дашбордов и автоматически загружает их в Grafana.

- **Image Renderer**: Отдельный компонент, который позволяет Grafana создавать PNG-изображения графиков для включения в уведомления об алертах. Он использует headless-браузер и является обязательным для отправки алертов с визуализациями в мессенджеры, такие как Slack или Telegram.

## 3. Практические сценарии

Ниже представлена пошаговая инструкция по установке и настройке Grafana.

### Шаг 1: Подключение репозитория Helm

Добавление официального репозитория Helm-чартов Grafana и его обновление:
```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

### Шаг 2: Создание файла конфигурации

Создайте файл `grafana-values.yaml` с основными параметрами. Этот файл определяет ключевые аспекты развертывания.

**Пример `grafana-values.yaml`:**
```yaml
# Настройка Ingress для внешнего доступа
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    # Для защиты можно использовать OAuth2 Proxy, развернутый отдельно
    # nginx.ingress.kubernetes.io/auth-url: "http://oauth2-proxy.default.svc.cluster.local/oauth2/auth"
    # nginx.ingress.kubernetes.io/auth-signin: "https://sso.your-domain.com/oauth2/start?rd=$request_uri"
  hosts:
    - host: grafana.your-domain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts:
        - grafana.your-domain.com
      secretName: grafana-tls

# Учетные данные администратора (рекомендуется использовать секреты)
admin:
  user: admin
  password: StrongPassword.123

# Включение персистентного хранилища для данных Grafana
persistence:
  enabled: true
  type: pvc
  size: 5Gi

# Указание публичного URL для корректной работы ссылок
grafana.ini:
  server:
    root_url: "https://grafana.your-domain.com"

# Включение автоматической загрузки дашбордов через sidecar
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"

# Включение рендеринга изображений для алертов
imageRenderer:
  enabled: true
```

### Шаг 3: Установка Grafana

Выполнение установки с помощью `helm install`, используя созданный файл конфигурации.
```bash
helm install grafana grafana/grafana \
  -f grafana-values.yaml \
  --namespace monitoring --create-namespace \
  --wait --atomic
```
- `--wait`: Ожидать завершения развертывания всех ресурсов.
- `--atomic`: Откатить релиз в случае неудачной установки.

### Шаг 4: Проверка установки

Проверка статуса подов и Ingress-ресурса Grafana.
```bash
# Проверка статуса пода
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Проверка созданного Ingress-ресурса
kubectl get ingress -n monitoring -l app.kubernetes.io/name=grafana
```
Убедитесь, что под находится в состоянии `Running`, а Ingress-ресурс корректно создан.

### Шаг 5: Доступ к Grafana

После успешного развертывания Grafana будет доступна по адресу, указанному в `ingress.hosts`. Для входа используйте учетные данные администратора.

## 4. Дополнительная информация

Для ознакомления со всеми доступными параметрами конфигурации Helm-чарта Grafana рекомендуется изучить его `values.yaml` по умолчанию.
```bash
helm show values grafana/grafana > grafana-default-values.yaml
```
Эта команда создаст файл `grafana-default-values.yaml` с полным списком опций и их значениями по умолчанию.
