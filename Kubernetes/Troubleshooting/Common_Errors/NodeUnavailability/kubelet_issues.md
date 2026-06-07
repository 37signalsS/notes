# Недоступность узла: Проблемы Kubelet

## Определения

**Сбой Kubelet** (Kubelet Issue) — ситуация, при которой агент Kubelet на узле не может нормально функционировать (процесс остановлен, не отвечает на запросы, не может подключиться к API-серверу), что приводит к переходу узла в статус `NotReady` или `Unknown`.

**Kubelet** — основной агент на каждом рабочем узле, отвечающий за регистрацию узла в кластере и управление жизненным циклом подов. Подробнее: [Kubelet](../../../Concepts/kubelet.md).

## Основные концепции

### Архитектура Kubelet (кратко)

| Компонент | Назначение |
|:----------|:-----------|
| **API Server Client** | Взаимодействие с Control Plane, получение PodSpec |
| **CRI (Container Runtime Interface)** | Интерфейс взаимодействия со средой выполнения (containerd/CRI-O) |
| **Health Checks** | Выполнение liveness и readiness проб для контейнеров |
| **Node Status Reporter** | Сбор и отправка условий узла (Ready, MemoryPressure и др.) |
| **Certificate Manager** | Управление TLS-сертификатами агента |

### Типичные режимы сбоев

| Режим сбоя | Статус узла | Вероятная причина |
|:-----------|:------------|:------------------|
| Процесс остановлен | `NotReady` / `Unknown` | Краш приложения, OOM kill, ручная остановка |
| Ошибка конфигурации | `NotReady` | Опечатки или несовместимые параметры в `config.yaml` |
| Истечение сертификатов | `NotReady` | Ошибка ротации сертификатов `kubelet-client` |
| CRI недоступен | `NotReady` | Сбой в работе containerd или CRI-O |

### Конфигурация и журналы

| Объект | Путь | Описание |
|:-------|:-----|:---------|
| **Основной конфиг** | `/var/lib/kubelet/config.yaml` | Параметры KubeletConfiguration |
| **Флаги запуска** | `/etc/default/kubelet` | Аргументы командной строки |
| **Сертификаты** | `/var/lib/kubelet/pki/` | Файлы для TLS-аутентификации |
| **Логи (systemd)** | `journalctl -u kubelet` | Основной инструмент диагностики |

## Практические сценарии

### Сценарий 1: Kubelet остановлен или не отвечает

**Симптомы:**

- Статус узла: `NotReady` или `Unknown`.
- Поды на узле перестают обновлять статус.

**Диагностика:**

```bash
# Проверка статуса системного сервиса
systemctl status kubelet

# Анализ последних записей в журнале
journalctl -u kubelet -n 50 --no-pager
```

**Решение:**

1. Если сервис в статусе `inactive`, попробуйте запустить его: `sudo systemctl start kubelet`.
2. Если сервис падает при запуске, изучите логи на предмет ошибок в `config.yaml` или нехватки ресурсов на узле.

### Сценарий 2: Проблемы с TLS-сертификатами

**Симптомы:**

- Kubelet работает, но в логах видны ошибки: `x509: certificate has expired`.
- Узел не может авторизоваться в API-сервере.

**Диагностика:**

```bash
# Проверка срока действия сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep -A 2 "Validity"

# Проверка статуса всех сертификатов (для кластеров kubeadm)
kubeadm certs check-expiration
```

**Решение:**
Подробные инструкции по ротации приведены в разделе [Управление сертификатами](../../../Operations/certificate_management.md).

```bash
# Принудительное обновление через kubeadm
sudo kubeadm certs renew all
sudo systemctl restart kubelet
```

### Сценарий 3: Kubelet не регистрирует узел

**Симптомы:**

- Процесс Kubelet активен, но узел отсутствует в выводе `kubectl get nodes`.
- В логах ошибки: `unable to register node ... forbidden`.

**Диагностика:**

1. Проверьте права доступа в логах: `journalctl -u kubelet | grep -i "forbidden"`.
2. Проверьте наличие файла `bootstrap-kubeconfig` (если это новый узел).
3. Проверьте сетевую доступность API-сервера с узла.

**Решение:**
Убедитесь, что токен присоединения (bootstrap token) актуален и Kubelet имеет права на создание CSR (Certificate Signing Request).

## Дополнительная информация

### Смежные концепции

- Обзор архитектуры: [Kubelet](../../../Concepts/kubelet.md)
- Управление сертификатами: [Operations: Certificate Management](../../../Operations/certificate_management.md)

### Другие причины недоступности

- Проблемы среды выполнения: [Container Runtime Issues](./runtime_issues.md)
- Сетевые проблемы узла: [Network Issues](./network_issues.md)
- Нехватка ресурсов (Pressure): [Resource Pressure](./resource_pressure.md)
- Плановое обслуживание: [Node Maintenance](./maintenance.md)
