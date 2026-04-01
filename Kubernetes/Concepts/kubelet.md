# Kubelet — агент Kubernetes на узле

## Определения

**Kubelet** — основной агент Kubernetes, работающий на каждой ноде кластера. Выполняется как системный сервис (systemd-юнит), а не как контейнер. Отвечает за регистрацию узла, запуск и мониторинг контейнеров, а также предоставление отчётности о состоянии узла в API-сервер.

**Ключевая роль:** Kubelet — это граница между декларативными описаниями подов из API и фактическим выполнением кода в контейнерах. Без kubelet узел остаётся просто сервером, не интегрированным в кластер.

## Основные концепции

### Принцип работы

| Этап | Описание |
|------|----------|
| **1. Регистрация узла** | При старте kubelet регистрирует узел в API-сервере, передавая информацию о ресурсах (CPU, память), IP-адресах и метках |
| **2. Получение заданий** | Kubelet использует механизм `watch` (длинные соединения) для наблюдения за API-сервером. При появлении Pod с `spec.nodeName`, равным имени узла, приступает к запуску |
| **3. Запуск контейнеров** | Kubelet обращается к container runtime (containerd, CRI-O) через CRI (Container Runtime Interface). Runtime создаёт контейнеры, настраивает изоляцию через namespace и cgroups |
| **4. Мониторинг и пробы** | Kubelet выполняет [livenessProbe](../Base/probes.md), [readinessProbe](../Base/probes.md), [startupProbe](../Base/probes.md) для проверки состояния приложений |
| **5. Отчётность** | Kubelet собирает состояние контейнеров (Running, Terminated, Waiting) и передаёт его в API-сервер |

### Конфигурация

Kubelet настраивается через конфигурационный файл (обычно `/var/lib/kubelet/config.yaml`):

```yaml
apiVersion: kubelet.config.k8s.io/v1
kind: KubeletConfiguration
cgroupDriver: systemd
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
kubeReserved:
  cpu: "200m"
  memory: "512Mi"
systemReserved:
  cpu: "100m"
  memory: "256Mi"
rotateCertificates: true
```

**Ключевые параметры:**

- `evictionHard` — пороги вытеснения подов при нехватке ресурсов
- `kubeReserved` / `systemReserved` — резервирование ресурсов для системных компонентов Kubernetes и ОС
- `rotateCertificates` — автоматическая ротация сертификатов

### Режимы работы

| Режим | Описание |
|-------|----------|
| **Управление через API** | Kubelet получает задания от API-сервера (основной режим) |
| **Статические поды** | Kubelet запускает поды из манифестов в каталоге `/etc/kubernetes/manifests` (используется для компонентов control plane в kubeadm) |

## Практические сценарии

### Проверка статуса kubelet

```bash
# Проверка статуса сервиса
systemctl status kubelet

# Просмотр логов
journalctl -u kubelet -n 100 --no-pager

# Проверка конфигурации
cat /var/lib/kubelet/config.yaml
```

### Диагностика проблем

**Симптомы:**

- Статус узла: `NotReady` или `Unknown`
- Kubelet не отвечает или не запускается

**Причины:**

- Сбой процесса kubelet
- Ошибка конфигурации
- Нехватка ресурсов
- Проблемы с сертификатами

**Решение:**

```bash
# Перезапуск kubelet
sudo systemctl restart kubelet

# Проверка сертификатов
openssl x509 -in /var/lib/kubelet/pki/kubelet.crt -text -noout | grep -A 2 "Validity"

# Обновление сертификатов (kubeadm)
sudo kubeadm certs renew all
sudo systemctl restart kubelet
```

### Статические поды

Для запуска статических подов разместите манифест в `/etc/kubernetes/manifests/`:

```yaml
# /etc/kubernetes/manifests/static-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: static-pod
spec:
  containers:
  - name: nginx
    image: nginx:1.25
```

Kubelet автоматически обнаружит манифест и запустит под. Такие поды **не управляются через API** — только через файловую систему.

## Дополнительная информация

**Важные особенности:**

* **Управляет только контейнерами:** Kubelet работает исключительно с подами и их контейнерами. Он не знает про Deployment, Service, Ingress — эти абстракции обрабатывает [kube-controller-manager](./control_plane_architecture.md).

* **Автономность при сбоях control plane:** Если API-сервер временно недоступен, kubelet продолжает работать с запущенными подами и следить за их состоянием. Новые поды назначить не сможет, но уже работающие не остановятся.

* **Связь через watch:** Вместо постоянного опроса (polling) kubelet использует механизм `watch` — длинные соединения с API-сервером для мгновенного получения обновлений. Это снижает нагрузку на API и ускоряет реакцию на изменения.

* **Пробы (Probes):** Kubelet выполняет проверки liveness, readiness, startup для определения состояния контейнеров. Подробнее: [Пробы](../Base/probes.md).

* **Безопасность:** Аутентификация kubelet происходит через TLS-сертификаты. Подробнее: [TLS и mTLS](../Security/tls_and_mtls_in_kubernetes.md).

* **Ротация сертификатов:** Сертификаты kubelet требуют периодической ротации. Подробнее: [Управление сертификатами](../Operations/certificate_management.md).

* **Диагностика проблем:** При статусе узла `NotReady` или `Unknown` см. [Проблемы с kubelet](../Troubleshooting/Common_Errors/NodeUnavailability/kubelet_issues.md).
