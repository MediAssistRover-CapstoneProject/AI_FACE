# Kế hoạch nối xác thực khuôn mặt với giao hàng MAR

Đối chiếu ngày 18/11/2026. BE đã triển khai code face và AI_FACE đã ready trên EC2; tính năng BE vẫn tắt, bản policy BE mới chưa push, nghiệm thu staff/camera/servo robot chưa hoàn tất.

## Trạng thái đã kiểm chứng

| Thành phần | Hiện trạng |
|---|---|
| BE production `main`, `555bf51` | Đã hợp nhất face: chọn `QR_CODE` hoặc `FACE_VERIFICATION`, template staff admin duyệt, phiên face và quyền mở ngăn do BE cấp. Luật hàng quan trọng chưa có trong bản production này. Source cục bộ mới đã bổ sung policy theo chặng, đang chờ push/deploy. |
| BE CI và production | Run [44304610743](https://github.com/MediAssistRover-CapstoneProject/BE_MAR/actions/runs/44304610743) thành công với SHA `555bf51ebdc95af231f496353defb9573a22fdd4`. SSM kiểm chứng JAR chứa lớp face; Flyway V62 thành công lúc `2026-11-18 12:32:44`. Đã chuẩn bị `/etc/mediassistrover/face.env` và unit drop-in với base URL/key, `FACE_ENABLED=false`; chưa restart BE hoặc bật face. |
| Kiểm tra BE cục bộ mới | 255 test, 0 failure, 0 error, 1 skipped; phần MySQL schema test bị bỏ qua. Kết quả này không thay thế nghiệm thu camera/servo. |
| Pi main `9699662` | Đã merge hỗ trợ face: scanner lấy ảnh ROS hiện tại, tối đa một lần gửi/giây và một request đang chờ; không chạy model nhận diện trên Pi. SSH tới Pi hiện timeout, chưa xác nhận được phiên bản/cấu hình đang cài hoặc readiness phần cứng. |
| `AI_FACE` main, `a65f7f5` + bản sửa cục bộ | FastAPI; YuNet phát hiện mặt, SFace tạo embedding ONNX 128 chiều; so khớp 1–1. Bản sửa đã có init-lock, warmup trước ready, native thread mặc định 1 và giới hạn một request, dư tải trả 429. |
| EC2 media `i-09f564686a122f182` | Đã cài systemd `face-ai`, private `172.31.35.139:8095`, release `3344185fbf4b448951d0d54c1915ba80617203cc`; health model ready, `liveness:false`. Voice/fall vẫn active. SG TCP8095 chỉ cho SG BE tới SG media, cả ingress/egress. |
| Triển khai và CI | AI service đã deploy thủ công bằng artifact kiểm tra. `.github/workflows/face-ci.yml` đã chuẩn bị nhưng chưa cấu hình GitHub variables/OIDC; chưa có tự động deploy qua CI. Hai ONNX có checksum đúng, nằm trong Git ignore. 20 test AI qua bằng dependency lock, không skipped; chỉ dùng ảnh công khai. Bản sửa BE/UI chính sách vẫn local, chưa push. |

Xung đột số migration cũ đã được xử lý: tuần tra dùng V61, face dùng V62. Không đổi nội dung/số của migration đã áp dụng. Các bước tiếp theo phải làm trên main mới, giữ các sửa MQTT, SOS, tuần tra và vị trí người té ngã.

## Phần có thể tận dụng

- `FaceAuthService`: BE chọn đúng người gửi/người nhận, template và avatar revision; Pi không được gửi kết quả `matched` hoặc tự chọn staff đích.
- So khớp thực hiện ngoài transaction; trước khi cấp quyền, BE kiểm tra lại robot, transport, job/step đang chạy, hủy job, hạn phiên và revision avatar. Phiên đã dùng không được dùng lại.
- Đổi avatar làm vô hiệu template và quyền face chưa sử dụng. AI lỗi, sai người hoặc hết hạn giữ ngăn khóa, không tự chuyển sang QR.
- Face thành công hoàn tất `AUTHENTICATE`; bước `CONTROL_HARDWARE/UNLOCK` vẫn dùng quyền do BE cấp, rồi xác nhận hàng, đóng nắp, khóa và xác nhận khóa như luồng hiện tại. AI không điều khiển servo.

## API đã có trong BE main đã deploy

Code API đã có trong artifact triển khai; khả năng dùng face vẫn phụ thuộc bật cấu hình, service AI, mẫu staff, workflow published và khả năng của Pi. Deploy JAR không có nghĩa đã có giao hàng face hoạt động xuyên suốt.

| API | Quyền và ý nghĩa |
|---|---|
| `POST /api/v1/delivery-requests` | STAFF/ADMIN; thêm `authenticationMethod: QR_CODE` hoặc `FACE_VERIFICATION`; bỏ trường này hiện mặc định QR. |
| `POST /api/v1/service-requests/{requestId}/submit` | Gửi đơn qua luồng hiện hành; BE chọn workflow published có phương thức phù hợp. |
| `GET /api/v1/staff/{accountId}/face-status` | STAFF/ADMIN; trả trạng thái, avatar revision; không trả embedding. |
| `POST /api/v1/admin/staff/{accountId}/face-review` | ADMIN; `{ "avatarVersion": "UUID đang xem", "approve": true }`; BE enroll từ avatar, gắn revision. ID là accountId. |
| `POST /api/v1/admin/workflows/staff-face-delivery-draft` | ADMIN; tạo draft, còn phải validate/publish. |
| `GET /api/v1/pi/jobs/{jobId}/face-auth` | Device JWT đúng robot; trả cửa sổ face đang hoạt động hoặc 204. MQTT `SERVER_HEARTBEAT.staffFaceScan` cũng công bố cửa sổ. |
| `POST /api/v1/pi/jobs/{jobId}/face-auth/verify` | Device JWT; `{sessionId, authJobStepId, transportSessionId, image}`; ảnh JPEG base64. Trả `{verified, reason}`, không trả template/điểm cosine. |

API nội bộ AI là `GET /health/ready`, `POST /v1/face/enroll`, `POST /v1/face/verify`. Hai POST dùng `X-Face-Service-Key`; giữ khóa trên BE và AI, không đưa lên Pi/FE. Model/pipeline đổi version buộc enroll và duyệt lại mẫu.

## Nghiệp vụ theo yêu cầu mới

Chính sách theo yêu cầu hiện tại: **người gửi luôn QR; người nhận hàng quan trọng dùng `FACE_VERIFICATION`; người nhận hàng thường dùng `QR_CODE`**. Không yêu cầu người nhận làm cả QR và face. Source BE cục bộ đã bổ sung; production `555bf51` chưa có chính sách mới này.

1. UI có cờ rõ ràng **Hàng quan trọng**, gửi `items[].sensitive`; phần ghi chú vẫn để mô tả. BE không suy đoán bảo mật chỉ từ từ khóa trong văn bản tự do. Chỉ cần một món `sensitive=true`, BE tính phương thức **chặng người nhận** là `FACE_VERIFICATION`; còn lại tính QR. Lưu snapshot phương thức trên đơn/job, không tin lựa chọn hạ cấp từ UI.
2. Kiểm tra lại ở create, submit/chọn workflow và ngay trước cấp quyền mở ngăn. Khi yêu cầu face mà AI/mẫu/workflow/Pi chưa sẵn sàng, trả lỗi rõ ràng, giữ khóa; không âm thầm chuyển QR.
3. Staff gửi trình QR đúng giao dịch; staff nhận quan trọng được so face 1–1 với **đúng người nhận được giao**. Không yêu cầu enroll mặt staff chỉ làm người gửi. Giữ graph mỗi chặng: MOVE → AUTHENTICATE đúng phương thức → UNLOCK → xác nhận hàng → xác nhận đóng nắp → LOCK → xác nhận đã khóa. Không thêm AUTH thứ hai hoặc quyền tổng hợp không cần thiết.
4. Quy tắc nghiệp vụ có thể là cấu hình có version; không hardcode tên staff, phòng SOS hoặc room ID. Staff thao tác trong phạm vi đơn/ca trực; admin duyệt avatar và quản lý chính sách. FE chỉ hiển thị phương thức BE tính, hướng dẫn nhìn camera và lý do retry; không quyết định mở servo.
5. Giữ session/challenge ngắn hạn gắn job/step/chặng/actor/robot/transport và tiêu thụ một lần; bổ sung rate limit phía server. Retry không gia hạn vô hạn. Mất mạng/hủy phiên vô hiệu quyền chưa dùng, không đổi sang phương thức yếu hơn.

## Tiến độ source mới và phần còn lại

- **P1 đã sửa cục bộ — policy:** `DeliveryAuthenticationPolicy` tính từ item persisted và phương thức của từng purpose; create/submit/workflow dùng cùng quy tắc. Production vẫn phải chờ bản BE mới.
- **P1 đã sửa cục bộ — UNLOCK:** kiểm tra cuối đối chiếu method bắt buộc của chặng và expected actor, bên cạnh job/purpose, hạn, AUTH, tokenVersion và avatar revision. Không dựa duy nhất vào kiểm tra ở bước trước.
- **P2 đã sửa cục bộ — reconnect:** `FaceAuthService` thay challenge chưa dùng sang transport mới trong cùng AUTH còn hợp lệ, vô hiệu challenge cũ và giữ **deadline gốc**. Không gia hạn tự động; phiên đã dùng/hết hạn/hủy vẫn bị từ chối.
- **P2 đã sửa cục bộ — hard-delete:** các service xóa job/workflow đã dọn quan hệ con `face_auth_session` trong transaction, tránh lỗi khóa ngoại. Không cần xóa dữ liệu trực tiếp để né lỗi.
- **P2 đã sửa cục bộ — runtime AI:** engine khởi tạo một lần, warmup ảnh tổng hợp trước ready; thiếu key/model hoặc lỗi warmup trả 503. Chỉ nhận một yêu cầu trước đọc body; dư tải 429 và không queue ảnh. Native inference có lock không chờ, native pool một thread mặc định.
- **Còn cần triển khai/nghiệm thu:** key private và service AI đã có; `FaceAiClient.enabled()` chỉ xét flag/key nên vẫn kiểm health trước bật BE. Còn push/deploy BE mới, CI variables/OIDC, workflow và mẫu người nhận. Đọc phiên bản/config Pi thực tế rồi kiểm end-to-end. Không bật face chỉ vì source đã có đủ class.

## Giới hạn cần giải quyết trước khi coi là bảo vệ hàng quan trọng

`AI_FACE` công bố `liveness:false`. Ngưỡng cosine 0.363 là điểm tương đồng, không phải 36,3% độ chính xác. Hiện một ảnh khớp là đủ; ảnh in/video có thể vượt nhận diện. Challenge chỉ gắn phiên và chống dùng lại **quyền**, không tự chứng minh ảnh là người sống; Pi kiểm tra độ mới frame cũng không thay thế chống giả mạo.

Vì vậy, bản hiện tại phù hợp demo có giám sát. Nếu nghiệm thu hàng quan trọng thực tế cần thêm liveness/PAD đã đánh giá trên camera thật, đồng bộ challenge và chuỗi frame. Depth camera hiện có chưa được sử dụng cho anti-spoof. Không hạ ngưỡng hoặc tuyên bố nhiều frame đã là liveness.

Camera VGA dùng được về hợp đồng ảnh: một mặt rõ, vùng mặt ít nhất 80×80 pixel, kiểm tra độ nét; góc camera thấp có thể cần hướng dẫn staff cúi/đứng gần. Không mở driver USB thứ hai. Kết quả smoke test bằng ảnh công khai không chứng minh tỷ lệ nhận sai trên staff thực tế.

## Tài nguyên và nơi chạy AI

SSM đo EC2 media `i-09f564686a122f182` lúc `2026-11-18 13:00 UTC`: `t4g.medium`, ARM64, 2 vCPU; RAM 3,73 GiB, dùng 0,77 GiB, available 2,97 GiB; swap 0; đĩa trống 15 GiB. Voice dùng khoảng 211 MiB theo cgroup, fall 85 MiB; LiveKit RSS khoảng 80 MiB. CPU lúc đo 99–100% idle, CloudWatch gần nhất khoảng 0,47–0,61%; CPUCreditBalance 576. Đây là mẫu lúc ít tải, chưa phải đo peak khi robot đang chạy tất cả luồng.

AI_FACE đã được cài thành **service riêng trên EC2 media hiện có**, chưa tạo thêm instance. YuNet/SFace dùng OpenCV CPU, không cần Torch/GPU; hai weights tổng 38.928.942 byte, khoảng 37,1 MiB. Kích thước weights không phải RAM runtime. Giữ Pi lấy frame, gửi request và nhận quyền; không chạy thêm model trên Pi để ưu tiên LiDAR/TF/AMCL/MOVE.

Service đang dùng một Uvicorn worker, OpenCV/BLAS một thread, một request face đang xử lý và không có hàng đợi inference; RAM giới hạn khởi điểm 512 MiB, CPU quota 50% của một vCPU, ưu tiên CPU thấp hơn voice. Preload/health warmup và init-lock đã có. `MemoryCurrent`/`MemoryPeak` sau kiểm tra là **162.861.056 byte ≈155,3 MiB**. Gửi ảnh trống tổng hợp VGA trả `NO_FACE`: lần đầu **90,8 ms**, các lần sau **45,3–47,6 ms**. Đây không phải benchmark xác thực staff hoặc tải nhiều robot; voice/fall vẫn active nhưng chưa đo đủ tải đồng thời để bảo đảm latency. Ảnh tối đa 12 triệu pixel có thể tạo nhiều buffer lớn, nên giữ nguồn robot VGA và giới hạn ảnh tải lên. Chỉ tách instance AI khi phép đo thực tế cho thấy cạnh tranh tài nguyên.

Key service đã tạo và lưu ở SecureString `/mediassistrover/face/service-key`; không in key trong tài liệu/log. BE đã có base URL/key trong file env được unit drop-in tham chiếu nhưng vẫn `FACE_ENABLED=false`; chưa restart BE để nhận cấu hình và chưa triển khai code policy mới.

T4g.medium hiện ở Unlimited, baseline CPU 20%, tích lũy 24 credit/giờ; tải kéo dài có thể tiêu credit/phát sinh phí. Tham khảo [AWS CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html). Không dùng số đo nhàn rỗi để cam kết latency hoặc FPS tuyệt đối.

## Thứ tự triển khai

1. BE code/migration face đã deploy thành công ở `555bf51`; Pi main `9699662` đã có code face. Giữ face tắt trong khi hoàn tất các khoảng trống P1/P2. Không áp dụng lại V62 hoặc sửa migration đã chạy. Đọc cấu hình/bản thực trên Pi và đối chiếu trước khi vá/bật.
2. Review/push/deploy bản BE/UI mới: sender luôn QR, receiver quan trọng face, receiver thường QR; method và expected actor được kiểm tra tại UNLOCK. Không sửa thuật toán MOVE, AMCL hoặc phanh để thêm face.
3. **Đã hoàn tất phần service AI:** dependency lock, hai ONNX checksum đúng, systemd private8095, giới hạn tài nguyên, key và SG BE→media. Health đã ready; HTTPS bên ngoài giữ nguyên. Chưa thực hiện xác thực staff hoặc mở servo để nghiệm thu.
4. Review/push workflow CI AI_FACE đã chuẩn bị; đặt `FACE_DEPLOY_ROLE_ARN`, `FACE_ARTIFACT_BUCKET`, `FACE_MEDIA_INSTANCE_ID` và quyền OIDC/S3/SSM. CI ARM64 verify model/test rồi deploy đúng artifact có checksum, health check và rollback. Secret ở root-only env EC2, không trong GitHub workflow. Push BE main chỉ deploy BE; AI_FACE chỉ tự deploy sau khi các biến/quyền được cấu hình.
5. Duyệt mẫu **staff nhận hàng quan trọng** với modelVersion hiện tại, tạo/validate/publish workflow sender-QR/receiver-face. Đồng bộ Pi khi stack dừng: `staff_face_enabled=true`, `unlock_policy=STAFF_VERIFIED`, camera đúng topic và PWM sẵn sàng. Không cài model hoặc file test lên Pi.
6. Bật cấu hình sau health và đối chiếu hoàn tất; đo trước/sau CPU/RAM peak, LiDAR/TF, độ trễ MOVE/voice và FPS WebRTC với fall/video/voice cùng hoạt động. Face chỉ lấy ảnh khi robot đứng yên ở bước bàn giao. Nếu đo không đạt thì giảm tải/cách ly tài nguyên hoặc tách instance; không mặc định khẳng định hệ thống sẽ mượt.

## Nghiệm thu tối thiểu

Hoàn thành một đơn thường QR→QR và một đơn quan trọng QR người gửi→face người nhận. Thử client gửi QR cho người nhận hàng quan trọng, grant sai method/actor, sai người ở sender/receiver, ảnh mờ/nhiều mặt, đổi avatar giữa lần xác minh, mất mạng, reconnect trong cùng AUTH, hủy job, dùng lại challenge và ca trực kết thúc. Kiểm tra challenge cũ bị vô hiệu và reconnect không kéo dài deadline; kiểm tra hard-delete trong môi trường thử có bản ghi face. Các ca bị từ chối phải không có quyền mở ngăn. Xác nhận đã khóa trước khi MOVE; không tạo job thừa hoặc sửa dữ liệu production để giả lập đã xác minh. Dùng bộ kiểm tra hiện có và phép thử tích hợp cần thiết, không đưa fixture/test lên robot.

Kiểm tra AI_FACE sau sửa: **20 test qua, không skipped**, dùng đúng `requirements.lock.txt`, hai model checksum đúng và fixtures NASA công khai; kiểm tra bash installer và whitespace diff qua. Có một cảnh báo deprecation từ Starlette TestClient, không phải lỗi test. Không dùng ảnh staff hoặc chứng minh accuracy thực tế bằng bộ test này.

Nguồn đối chiếu: `AI_FACE/app.py`, `AI_FACE/ROBOT_CAMERA_REVIEW.md`; BE deployed `555bf51` và bản sửa local `DeliveryAuthenticationPolicy`, `FaceAuthService`, `OperationAuthorizationService`, hard-delete, UI; CI run nêu trên, SSM deployment/health/resource checks; Pi main `9699662`, `staff_face.py`, `step_worker.py`. AI release `3344185fbf4b448951d0d54c1915ba80617203cc` đã chạy; source BE/AI mới chưa push và BE face chưa bật.
