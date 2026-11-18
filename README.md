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

Hướng dẫn tích hợp và nghiệm thu: [FACE_DELIVERY.md trong BE_MAR](https://github.com/MediAssistRover-CapstoneProject/BE_MAR/blob/feature/staff-face-delivery/docs/FACE_DELIVERY.md).

## Giới hạn bản demo

Chưa có liveness/chống ảnh in hoặc video. Chỉ chạy có giám sát. Không coi việc khớp nhiều frame hoặc ảnh avatar được duyệt là chống giả mạo. Chưa nghiệm thu robot thật hoặc triển khai migration lên database đang vận hành.


## Test hai ảnh trên Windows

Restart service sau khi cập nhật code. Trong PowerShell thứ hai, đặt `FACE_SERVICE_KEY` trùng service rồi chạy:

```powershell
.\test_images.ps1 -AvatarPath "$env:USERPROFILE\Desktop\avatar.jpg" -CameraPath "$env:USERPROFILE\Desktop\camera.jpg"
```

Script tạo mẫu mới rồi so ảnh camera, không in template. `accepted` là kết quả tạo mẫu; `matched` là kết quả so sánh. Response bổ sung `quality`: kích thước xử lý, kích thước mặt và điểm nét; khi `reason=LOW_QUALITY`, xem `quality.issue` (`FACE_TOO_SMALL`, `FACE_TOO_BLURRY`, `INVALID_FACE_FEATURE`). Không ghi các ảnh cá nhân vào repository.

Pipeline v2 xử lý hướng EXIF, giới hạn ảnh đầu vào 12 triệu pixel/2 MiB, chỉ thu nhỏ về cạnh dài tối đa 960 pixel. Độ nét được đo sau khi thu nhỏ vùng mặt về cạnh dài tối đa 160 pixel; không phóng lớn mặt nhỏ hoặc làm sắc nét để vượt kiểm tra. Ngưỡng cosine vẫn là 0.363. Pipeline mới đổi `modelVersion`: mẫu cũ phải tạo lại và duyệt lại khi dùng với BE. Ngưỡng chất lượng là heuristic cho demo, chưa hiệu chuẩn bằng dữ liệu camera staff thực tế.
