# AI_FACE — xác thực khuôn mặt giao hàng

Service Python riêng chạy trên máy tính/server. Pi gửi JPEG đến backend; backend chọn mẫu của đúng người gửi hoặc người nhận, gọi service rồi cấp quyền mở ngăn. Service không điều khiển servo, không tìm danh tính trong toàn bộ danh sách staff và không lưu ảnh camera.

## Cài và chạy

Python 3.11, CPU; model ONNX YuNet/SFace từ OpenCV Zoo. Manifest giữ URL theo commit và SHA-256. Không thay model mà giữ nguyên mẫu đã duyệt.

```powershell
cd C:\Users\Admin\Desktop\voice\AI_FACE
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe download_models.py
# Đặt FACE_SERVICE_KEY trong môi trường: chuỗi ngẫu nhiên ít nhất 32 ký tự.
# Dùng cùng giá trị cho backend. Không commit secret vào Git.
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8095
```

Trên Linux dùng `.venv/bin/python`. Nếu BE ở máy khác, cấu hình một endpoint mạng riêng/TLS để BE truy cập; không công khai service ra Internet. Mặc định bind loopback dành cho BE cùng máy.

`GET /health/ready` trả 200 khi model/checksum và khóa service hợp lệ. Ngưỡng `FACE_COSINE_THRESHOLD` mặc định `0.363`; đây là điểm cosine, không phải phần trăm chính xác. Chỉ thay sau khi đo false accept/false reject bằng camera thực tế.

Service nạp và warmup hai model bằng ảnh tổng hợp khi khởi động, trước khi báo ready. Lỗi cấu hình/model giữ health ở 503; sửa xong phải restart service. Engine chỉ được khởi tạo một lần kể cả nhiều request đồng thời. `FACE_NATIVE_THREADS` mặc định 1, chỉ nhận 1 hoặc 2; deployment dùng chung EC2 media cố định 1. OpenCV và các pool BLAS được giới hạn trước khi nạp model.

Mỗi process chỉ nhận một yêu cầu face tại một thời điểm, kiểm tra trước khi đọc ảnh. Không có hàng đợi inference: request vượt tải trả HTTP 429 `FACE_BUSY`, `Retry-After: 1`; model chưa sẵn sàng trả 503. BE/Pi giữ retry trong deadline hiện có, không chuyển sang QR hoặc mở khóa khi lỗi. Health vẫn có thể được đọc khi đang xử lý. Response đặt `Cache-Control: no-store`.

## API nội bộ

Hai POST yêu cầu header `X-Face-Service-Key`.

| API | JSON vào | Kết quả |
|---|---|---|
| `/v1/face/enroll` | `image`: base64 JPEG/PNG/WebP | `accepted`, `reason`, `template`, `modelVersion` |
| `/v1/face/verify` | `image`, `template` 128 số, `modelVersion` | `matched`, `reason`, `score`, `modelVersion` |
| `/health/ready` | Không | `ready`, `modelVersion`, `liveness:false` |

Ảnh tối đa 2 MiB và 12 triệu pixel. Ảnh không mặt/nhiều mặt/mặt nhỏ hoặc mờ bị từ chối. Model thay đổi buộc tạo lại mẫu và admin duyệt lại. HTTP lỗi, model thiếu hoặc checksum sai không tạo kết quả khớp.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe tests/download_fixtures.py
.\.venv\Scripts\python.exe -m pytest -q
```

Fixtures là ảnh công khai NASA được phân phối cùng scikit-image/matplotlib; script ghi nguồn, ảnh không commit. Test model thật thử cùng người sau đổi sáng, khác người, nhiều mặt, ảnh mờ và ảnh trống. Đây chỉ là smoke test, chưa là đo chất lượng trên staff/camera robot.

Hướng dẫn tích hợp và nghiệm thu: [FACE_DELIVERY.md trong BE_MAR](https://github.com/MediAssistRover-CapstoneProject/BE_MAR/blob/main/docs/FACE_DELIVERY.md), [kế hoạch tích hợp](docs/FACE_DELIVERY_INTEGRATION_PLAN.md). Chính sách mục tiêu: **người gửi luôn quét QR; người nhận hàng quan trọng xác thực face; người nhận hàng thường quét QR**. BE tính từ `items[].sensitive`, không suy luận từ ghi chú tự do. Mỗi chặng chỉ yêu cầu đúng phương thức của chặng đó.

Staff upload avatar bằng `POST /api/v1/staff/me/avatar` (multipart `file`) vào S3, chưa tự động được nhận diện/duyệt. Admin lấy `GET /api/v1/staff/{accountId}/face-status` rồi gọi `POST /api/v1/admin/staff/{accountId}/face-review` với đúng `avatarVersion` và `approve:true`. BE đọc ảnh S3, gọi enroll, lưu template128 và modelVersion riêng trong DB; chỉ trạng thái READY mới dùng cho người nhận. Đổi/xóa avatar hủy mẫu và quyền face chưa dùng; AI không lưu ảnh robot.

Bản BE local mới giới hạn avatar riêng ở 2 MiB trước upload, giữ ảnh khi sửa hồ sơ mà bỏ trường `url`, vẫn cho xóa bằng `url:null` rõ ràng hoặc endpoint xóa avatar. Ảnh cũ lớn hơn giới hạn được báo `FACE_AVATAR_TOO_LARGE` khi duyệt. Response duyệt có thêm `reason` để hướng dẫn khi không thấy mặt/nhiều mặt/mờ/mặt quá nhỏ; template không được trả cho staff/Pi. Model đổi báo `FACE_MODEL_CHANGED`, cần enroll/duyệt lại; dư tải báo `FACE_AI_BUSY`, chỉ retry trong deadline. Những sửa BE này vẫn chờ push/deploy. Xóa avatar khỏi hồ sơ không tự xóa object S3 có thể đang được dùng chung.

## Cài trên EC2 media và CI

Đã cài service `face-ai` trên EC2 media `i-09f564686a122f182`, private `172.31.35.139:8095`, release `3344185fbf4b448951d0d54c1915ba80617203cc`. Health xác nhận model ready, `liveness:false`. Security Group TCP8095 giới hạn từ SG của BE tới SG media ở cả ingress/egress, không mở Internet. `deploy/face-ai.service`, `deploy/install-face.sh` và `.github/workflows/face-ci.yml` đã có trong source; variables/OIDC cho tự động deploy chưa cấu hình.

Đã đo ảnh trống tổng hợp VGA: lần đầu 90,8 ms, các lần sau 45,3–47,6 ms, kết quả `NO_FACE`; đây không phải benchmark nhận diện staff. `MemoryCurrent`/`MemoryPeak` tại lần đo là 162.861.056 byte, khoảng 155,3 MiB; voice và fall vẫn active. Chưa đo tải đồng thời đủ để cam kết độ trễ camera/voice.

Trên BE đã chuẩn bị `/etc/mediassistrover/face.env` và systemd drop-in chứa base URL/key, `FACE_ENABLED=false`; chưa restart BE hoặc bật tính năng, chưa push bản BE policy mới. Key được lưu bằng SecureString `/mediassistrover/face/service-key`, không ghi giá trị vào tài liệu/log.

Service riêng dùng user `marface`, `/opt/mar-face/current`, một worker, một native thread, port 8095; giới hạn thử nghiệm RAM 512 MiB, CPU 50% của một vCPU. Cần đo peak và độ trễ cùng voice/fall/WebRTC, không coi giới hạn này là cam kết hiệu năng. Không cài model lên Pi.

Installer yêu cầu `/etc/mediassistrover/face-ai.env`, owner root, mode 600; cấu hình mẫu dưới đây để tham khảo khi cài lại, **không đưa key thật lên Git**:

```ini
FACE_BIND_HOST=172.31.35.139
FACE_NATIVE_THREADS=1
FACE_SERVICE_KEY=<chuoi-ngau-nhien-it-nhat-32-ky-tu>
```

IP trên là private IP EC2 media tại lần đối chiếu; kiểm tra lại trước cài. Có thể dùng loopback nếu BE cùng máy. Installer chỉ chấp nhận loopback hoặc IPv4 RFC1918, không bind `0.0.0.0`/public IP. Security Group chỉ cho private IP hoặc SG của BE tới TCP8095; không mở Internet. BE đặt `FACE_BASE_URL=http://<private-ip>:8095` và cùng key; giữ `FACE_ENABLED=false` tới khi API/worker/workflow/mẫu đã sẵn sàng. Không cần TLS giữa hai service nếu dùng cấu hình private VPC đã chọn; HTTPS ngoài hệ thống giữ nguyên.

CI verify chạy ARM64, cài dependency lock, tải/checksum model theo manifest và fixtures công khai, chạy bộ kiểm tra hiện có rồi đóng gói artifact gồm code và model đã kiểm tra. Model/ảnh staff không được commit; artifact không chứa file test hoặc credentials. Deploy lấy **đúng artifact đã verify**, kiểm checksum, chuyển S3/SSM theo cơ chế dự án và gọi installer. Installer kiểm model/env, đổi symlink release, kiểm readiness và rollback nếu lỗi; không tự đổi firewall hoặc bật face trên BE/Pi.

Thiết lập GitHub repository variables sau khi cấp OIDC role phù hợp:

- `FACE_DEPLOY_ROLE_ARN`: role deploy chỉ tới bucket/instance chỉ định.
- `FACE_ARTIFACT_BUCKET`: bucket artifact đang dùng của dự án.
- `FACE_MEDIA_INSTANCE_ID`: `i-09f564686a122f182` nếu vẫn dùng EC2 media hiện tại.

Khi các biến/quyền và env trên EC2 đã có, push `main` chạy verify rồi deploy. PR chỉ verify; thiếu `FACE_DEPLOY_ROLE_ARN` thì deploy được bỏ qua. Sửa source cục bộ hoặc push BE không tự triển khai AI_FACE. Không có key service trong GitHub workflow.

## Giới hạn bản demo

Chưa có liveness/chống ảnh in hoặc video. Chỉ chạy có giám sát. Không coi việc khớp nhiều frame hoặc ảnh avatar được duyệt là chống giả mạo. BE đã deploy migration face V62 ngày 18/11/2026 và AI_FACE đã ready trên EC2; tính năng BE vẫn tắt, nghiệm thu staff/camera/servo robot chưa hoàn tất.


## Test hai ảnh trên Windows

Restart service sau khi cập nhật code. Trong PowerShell thứ hai, đặt `FACE_SERVICE_KEY` trùng service rồi chạy:

```powershell
.\test_images.ps1 -AvatarPath "$env:USERPROFILE\Desktop\avatar.jpg" -CameraPath "$env:USERPROFILE\Desktop\camera.jpg"
```

Script tạo mẫu mới rồi so ảnh camera, không in template. `accepted` là kết quả tạo mẫu; `matched` là kết quả so sánh. Response bổ sung `quality`: kích thước xử lý, kích thước mặt và điểm nét; khi `reason=LOW_QUALITY`, xem `quality.issue` (`FACE_TOO_SMALL`, `FACE_TOO_BLURRY`, `INVALID_FACE_FEATURE`). Không ghi các ảnh cá nhân vào repository.

Pipeline v2 xử lý hướng EXIF, giới hạn ảnh đầu vào 12 triệu pixel/2 MiB, chỉ thu nhỏ về cạnh dài tối đa 960 pixel. Độ nét được đo sau khi thu nhỏ vùng mặt về cạnh dài tối đa 160 pixel; không phóng lớn mặt nhỏ hoặc làm sắc nét để vượt kiểm tra. Ngưỡng cosine vẫn là 0.363. Pipeline mới đổi `modelVersion`: mẫu cũ phải tạo lại và duyệt lại khi dùng với BE. Ngưỡng chất lượng là heuristic cho demo, chưa hiệu chuẩn bằng dữ liệu camera staff thực tế.
