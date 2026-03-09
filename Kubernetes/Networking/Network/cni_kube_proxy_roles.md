# CNI и kube-proxy: Индекс

> **Файл декомпозирован.** Исходное содержимое разделено на тематические заметки:

## Структура

| Файл | Описание |
|------|----------|
| [definitions.md](./CNI/definitions.md) | Определения, разделение ролей CNI и kube-proxy |
| [ipvs.md](./CNI/ipvs.md) | Детальный обзор IPVS: алгоритмы, методы перенаправления |
| [ebpf.md](./CNI/ebpf.md) | Решения на базе eBPF: замена kube-proxy, установка Calico eBPF |
| [ipam.md](./CNI/ipam.md) | Управление IP-адресами: host-local, calico-ipam, dual-stack |
| [selection_and_external_access.md](./CNI/selection_and_external_access.md) | Выбор CNI, IP Advertisement, DSR, архитектура с LB + Ingress |

## Навигация

* [Сетевая модель Kubernetes](./network_overview.md)
* [NetworkPolicy](../NetworkPolicy/)
