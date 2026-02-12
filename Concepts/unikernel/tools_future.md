# Инструменты и будущее Unikernels

## Инструменты и фреймворки

### UniK (Unikernel Compiler)

```bash
# Установка
go get -u github.com/solo-io/unik

# Создание unikernel из Go приложения
unik build --name my-go-app --path ./myapp --language go --provider virtualbox

# Запуск
unik run --instanceName my-go-app-instance --imageName my-go-app
```

### OPS (NanoVMs)

```bash
# Установка
curl https://ops.city/get.sh -sSfL | sh

# Создание образа
ops load node_v14.2.0 -a myapp.js

# Запуск
ops run myapp

# Деплой в облако
ops image create myapp -t gcp -c config.json
ops instance create myapp -t gcp -z us-west1-b
```

**Поддерживаемые языки:**
- C, C++, Go, Node.js, Python, Ruby, Java, Rust, и др.

## Будущее Unikernels

### AWS Firecracker

AWS Firecracker — это virtualization technology, использующая MicroVMs:

```
Firecracker = KVM + Minimal device model + Fast boot

- Boot time: 125ms
- Memory overhead: < 5MB
- Density: 1000s MicroVMs per host
- Используется в AWS Lambda и Fargate
```

### WebAssembly (Wasm) + Unikernels

```
WebAssembly как "легкий unikernel":

┌─────────────────────────────────────────────────────────────┐
│                    WASM RUNTIME                             │
│              (Wasmtime, Wasmer, WasmEdge)                   │
├─────────────────────────────────────────────────────────────┤
│                    WASM MODULE                              │
│              (Sandboxed, portable)                          │
├─────────────────────────────────────────────────────────────┤
│                    HOST OS / Container                      │
└─────────────────────────────────────────────────────────────┘

Преимущества:
- Near-native performance
- Sandbox без hypervisor
- Поддержка множества языков
- Cloud-native
```

## Сравнение с альтернативами

| Технология | Размер | Безопасность | Производительность | Гибкость |
|------------|--------|--------------|-------------------|----------|
| **VM** | Большой | Средняя | Средняя | Высокая |
| **Container** | Средний | Средняя | Высокая | Высокая |
| **Unikernel** | Маленький | Высокая | Очень высокая | Низкая |
| **Wasm** | Маленький | Высокая | Высокая | Средняя |

## Дополнительная информация

- [MirageOS](https://mirage.io/)
- [IncludeOS](https://www.includeos.org/)
- [OSv](http://osv.io/)
- [Rumprun](https://github.com/rumpkernel/rumprun)
- [UniK](https://github.com/solo-io/unik)
- [OPS/NanoVMs](https://ops.city/)
- [AWS Firecracker](https://firecracker-microvm.github.io/)
