# RKE: Управление и поиск неисправностей

## Определения

**поиск неисправностей (troubleshooting)** — процесс диагностики и устранения проблем в работе Kubernetes-кластера.

**ротация сертификатов** — периодическая замена TLS-сертификатов компонентов кластера для поддержания безопасности.

**RKE CLI** — утилита командной строки для развертывания и управления кластерами RKE через YAML-конфигурацию.

## Базовые концепции

### Компоненты управления RKE

* **Rancher UI** — графический интерфейс для визуального управления, мониторинга и ротации сертификатов.
* **RKE CLI** — инструмент для управления жизненным циклом кластера (создание, обновление, удаление, бэкапы).
* **kubectl** — стандартная утилита для взаимодействия с API Kubernetes (применяется после настройки доступа).
* **Cattle Cluster Agent** — компонент на узлах, обеспечивающий связь между кластером и Rancher Server.

### Жизненный цикл сертификатов

* Срок действия сертификатов RKE по умолчанию составляет 1 год.
* Ротация возможна автоматически через Rancher UI или вручную через RKE CLI.
* При истечении сертификатов доступ через `kubectl` блокируется.

## Практические сценарии

### Управление кластером через RKE CLI

**Установка RKE CLI:**

```bash
# Скачивание бинарного файла (Linux)
curl -L https://github.com/rancher/rke/releases/download/v1.6.0/rke_linux-amd64 -o rke
chmod +x rke
sudo mv rke /usr/local/bin/

# Проверка версии
rke --version
```

**Развертывание и обновление:**

1. Подготовка конфигурации `cluster.yml` (узлы, роли, настройки etcd).
2. Запуск развертывания:

   ```bash
   rke up --config cluster.yml
   ```

3. После успешного завершения создается `kube_config_cluster.yml`.

**Удаление кластера:**

```bash
rke remove --config cluster.yml
```

### Поиск и устранение неисправностей (Специфика RKE)

Для общей диагностики подов и узлов используйте **[Обзор поиска неисправностей в Kubernetes](../../Troubleshooting/troubleshooting_overview.md)**. Ниже приведены специфические для RKE сценарии.

**Проблема: Истечение срока действия сертификатов**

Симптом: Ошибка `x509: certificate has expired` при выполнении команд `kubectl`.

* **Решение через Rancher UI:** `Cluster Management` → Выбор кластера → `⋮` → `Rotate Certificates`.
* **Решение через RKE CLI:**

  ```bash
  rke cert rotate --config cluster.yml
  ```

**Проблема: Доступ к API Server**

Если кластер не отвечает, проверьте доступность порта API (6443) на узлах Control Plane:

```bash
# Проверка доступности порта
nc -zv <rke-api-ip> 6443

# Проверка статуса контейнеров на узле через Docker (RKE запускает компоненты в контейнерах)
docker ps | grep kube-apiserver
```

**Проблема: Потеря кворума etcd**

Если более половины узлов `etcd` недоступны, кластер переходит в режим "только чтение" или становится недоступным.

* **Восстановление из снимка (snapshot) через RKE CLI:**

  ```bash
  rke etcd snapshot-restore --name <snapshot-name> --config cluster.yml
  ```

### Интеграция с CI/CD

При использовании RKE в пайплайнах рекомендуется использовать ServiceAccount с ограниченными правами.

**Пример для GitLab CI:**

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  variables:
    KUBE_CONFIG: $RKE_KUBECONFIG  # Закодированный в Base64 файл конфига
  script:
    - echo $KUBE_CONFIG | base64 -d > /tmp/kubeconfig
    - export KUBECONFIG=/tmp/kubeconfig
    - kubectl apply -f k8s/
```

## Дополнительная информация

**Резервное копирование etcd:**

Рекомендуется настроить автоматическое сохранение снимков `etcd` в S3-совместимое хранилище в секции `services.etcd` файла `cluster.yml`.

**См. также:**

* [RKE: Основные концепции](./rke_concepts.md)
* [RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)
* [Обзор поиска неисправностей в Kubernetes](../../Troubleshooting/troubleshooting_overview.md)
