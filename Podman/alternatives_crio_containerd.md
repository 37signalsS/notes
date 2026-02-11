# Другие альтернативы: CRI-O, Containerd

CRI-O и containerd — два распространённых контейнерных рантайма, ориентированных на производственные кластеры и соответствие спецификациям OCI. Они решают близкие задачи, но имеют различный фокус и архитектурные решения, что влияет на выбор в конкретной инфраструктуре.

## Что такое CRI-O

CRI-O — легковесный рантайм, созданный специально для Kubernetes и строго реализующий интерфейс CRI (Container Runtime Interface). Его цель — быть «тонким» слоем между kubelet и OCI-рантаймами (чаще runc или crun), без лишних возможностей, не связанных с Kubernetes.

**Ключевые компоненты:**

*   `kubelet` общается с CRI-O по gRPC (CRI).
*   `conmon` отслеживает жизненный цикл процессов контейнеров, собирает логи в CRI-формате и управляет TTY.
*   OCI-рантаймы (`runc`/`crun`) запускают процессы контейнеров.
*   Подсистема хранения использует драйверы `overlayfs`, `devicemapper`, `btrfs` и др.
*   Поддержка дополнительных рантаймов (например, Kata, gVisor) через `runtimeHandler`.

Важные свойства: минимализм, тесная интеграция с SELinux/AppArmor/seccomp, стабильная совместимость с Kubernetes-релизами.

## Что такое containerd

`containerd` — промышленный рантайм общего назначения, входящий в экосистему CNCF. Изначально выделен из Docker и используется им как «движок», но работает и автономно. Он управляет жизненным циклом изображений и контейнеров, снапшоттерами и выполняет задачи, необходимые как Kubernetes, так и другим потребителям.

**Ключевые компоненты:**

*   Демон `containerd` с CRI-плагином для `kubelet`.
*   `content store` и `snapshotters` (overlayfs, btrfs, zfs, stargz и др.).
*   `containerd-shim v2` изолирует жизненный цикл контейнера от демона.
*   OCI-рантаймы (`runc` по умолчанию) и альтернативы (Kata, gVisor).
*   Экосистема плагинов и инструментов (`ctr` — низкоуровневый CLI, `nerdctl` — привычный UX для пользователей Docker CLI).

Сильные стороны: расширяемость, богатая экосистема, рациональная производительность и поддержка продвинутых форматов образов.

## Сравнение и выбор

| Критерий | CRI-O | containerd |
| :--- | :--- | :--- |
| **Назначение** | Только Kubernetes (строгий CRI) | Общего назначения + CRI |
| **Демон/процессы**| crio + conmon | containerd + shims |
| **Экосистема** | Умеренная, фокус на K8s | Широкая, плагины и snapshotters |
| **Rootless** | Поддерживается (чаще с crun) | Поддерживается (userns, rootless режим) |
| **Рантаймы изоляции** | Kata, gVisor через handlers | Kata, gVisor как runtime v2 |
| **Логи** | CRI-логирование через conmon | CRI-логирование через CRI-плагин |
| **Где часто применяют** | Дистрибутивы с упором на K8s | Управляемые кластеры, edge, универсальные сценарии |

**Практические соображения выбора:**

*   Нужен минимализм и строгое следование CRI без лишнего — **CRI-O**.
*   Важна расширяемость, единый рантайм вне и внутри Kubernetes, необычные снапшоттеры — **containerd**.
*   Оба варианта стабильны и широко применяются в продакшене, поддерживают OCI-образы и безопасность на уровне ядра.

## Минимальные конфигурации и команды

Указать `kubelet` использовать `containerd`:

```ini
# /etc/systemd/system/kubelet.service.d/10-kubeadm.conf
Environment="KUBELET_KUBEADM_ARGS=--container-runtime=remote --container-runtime-endpoint=unix:///run/containerd/containerd.sock"
```

Генерация и правка конфига `containerd` (включая cgroups systemd):

```arduino
containerd config default > /etc/containerd/config.toml
# в [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
# SystemdCgroup = true
systemctl restart containerd
```

Базовая настройка CRI-O (менеджер cgroup):

```ini
# /etc/crio/crio.conf
[crio.runtime]
cgroup_manager = "systemd"
```

Проверка работы через `crictl`:

```nginx
crictl info
crictl images
crictl pods
```

Низкоуровневые операции:

```bash
# containerd
ctr images pull docker.io/library/nginx:alpine
ctr run --rm -t docker.io/library/nginx:alpine test

# CRI-O (через crictl)
crictl pull docker.io/library/nginx:alpine
crictl runp pod-config.json
crictl create <pod-id> container-config.json pod-config.json
crictl start <container-id>
```
