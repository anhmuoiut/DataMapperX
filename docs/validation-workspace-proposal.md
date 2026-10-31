# Đề xuất: Validation & Reports thành workspace độc lập

Trạng thái: **Revision 3** (30/10/2026). **Giai đoạn 0 đã được triển khai** (kết quả ở mục 16) và đang chờ xác nhận hoàn thành. Giai đoạn 1 trở đi **chưa** được duyệt.

Thứ tự ưu tiên: độ chính xác thống kê → toàn vẹn dữ liệu → báo cáo đúng → giao diện đơn giản.
Mục tiêu: phân tích và báo cáo đáng tin cậy như Minitab, nhưng đơn giản, và **không ảnh hưởng chức năng Data Mapping và Export Excel hiện tại**.
Kết quả chỉ được gọi là "tương đương Minitab" sau khi qua Golden Test (mục 12). Trước đó, trạng thái là `Pending Minitab Verification`.

## 0. Thay đổi

**Revision 3 (duyệt Giai đoạn 0):**
- D2: cơ chế xác nhận Capability chia ba mức (Information / Warning / Critical); phân biệt "người dùng đã đọc cảnh báo" với "điều kiện thống kê thực sự được đáp ứng"; thêm ổn định quá trình và giả định phân phối chuẩn vào thiết kế Capability Evaluation. Giai đoạn 0 chỉ chuẩn bị cấu trúc dữ liệu, không có giao diện xác nhận.
- D12 (mới): ba thành phần độc lập: Statistical Metrics, Evaluation Status, Validation Status. Trạng thái `Pending Minitab Verification` / `Minitab Verified` là trạng thái của phương pháp tính, không thay thế Validation Status của từng dataset.
- D13 (mới): fingerprint thống kê tách khỏi provenance.
- Kết quả và báo cáo lưu tiêu chí đã dùng, phiên bản tiêu chí và trạng thái xác nhận.
- Mục 15 (mới): điều kiện duyệt Giai đoạn 0, quy tắc dừng, nội dung báo cáo sau khi hoàn thành.
- Tên trạng thái: giữ nguyên hằng số hiện có (`CONDITIONAL PASS`, `N/A`); trong tài liệu này CAUTION ≙ CONDITIONAL PASS và Not Evaluated ≙ N/A. Việc đổi tên (nếu cần) quyết định ở Giai đoạn 1.

**Revision 2 so với Revision 1:**

- D1: Cpk/Ppk không còn cố định Cpk; chỉ số quyết định cấu hình theo Customer / Study Purpose / WI. Thêm xử lý một phía.
- D2: thêm tách biệt MSA và Process Capability; Capability không tự động PASS/FAIL khi điều kiện chưa được xác nhận.
- D3: tách ba loại thứ tự (Acquisition, Worksheet, Custom); không coi thứ tự RawData.xlsx là thứ tự thu thập.
- D5: phân biệt One Appraiser và Crossed; không tự xem Nest/Slot là Operator; không làm Expanded/Nested ở phiên bản đầu.
- Sửa quy tắc Gage Resolution (đảo dấu bất đẳng thức, đối chiếu lại WI 8.3.4).
- Thêm Quick Analysis, ba chỉ số ưu tiên, nút About / Calculation Details.
- Thêm sổ kiểm chứng Minitab và quy trình Golden Test.
- Giai đoạn 0 thu hẹp lại: chỉ nền kiến trúc, regression test trước khi refactor, **không đổi UI, Data Mapping, Export, công thức thống kê**.
- Bổ sung tiêu chí chấp nhận AC9–AC20 và tiêu chí thoát Giai đoạn 0.

## 1. Các quyết định

| # | Quyết định | Căn cứ |
|---|---|---|
| D1 | **Cpk/Ppk:** hiển thị khi đủ điều kiện tính. Mặc định ưu tiên Cpk cho nghiên cứu Process Capability thông thường. Chỉ số quyết định và ngưỡng **cấu hình theo Customer / Study Purpose / WI**; nếu WI yêu cầu Ppk thì Ppk quyết định. Đổi tiêu chí chỉ chạy lại Evaluation. Chỉ có một giới hạn spec thì dùng chỉ số một phía có nhãn rõ (CPU/CPL, Cpk/Ppk một phía); Cp/Pp là N/A, không tự tạo giá trị hai phía. | Người dùng; WI 8.4.1 (Ppk > 1.33 khi đổi script), 8.9 (Cp/Cpk > 1.33) |
| D2 | **Capability** phân tích toàn bộ N phép đo. Cảnh báo chia ba mức (mục 5.3): *Information* (khuyến nghị, không cần xác nhận), *Warning* (cho phân tích, nhưng phải xác nhận điều kiện áp dụng trước khi dùng kết quả để đánh giá), *Critical* (dữ liệu không hợp lệ hoặc không tính đúng được: không bao giờ PASS/FAIL). Người dùng luôn xem được metrics (preview). **Xác nhận của người dùng không phải bằng chứng điều kiện thống kê được đáp ứng.** Dữ liệu GRR (ví dụ 30 SN × 3 lần đo) không được mặc định dùng để kết luận năng lực quá trình. | Người dùng; Minitab: subgroup hợp lý, quy trình ổn định, phân phối chuẩn |
| D3 | **Ba loại thứ tự:** *Acquisition Order* (thứ tự đo thực tế, từ timestamp hoặc run order đáng tin cậy); *Worksheet Order* (giữ nguyên thứ tự dòng dữ liệu); *Custom Order* (người dùng chủ động chọn). Không tự sắp xếp lại. **Không** coi thứ tự RawData.xlsx (đã sắp theo SN) là thứ tự thu thập. Không có Acquisition Order đáng tin cậy thì vẫn chạy được theo Worksheet Order nhưng có cảnh báo và kết quả không được xem là năng lực quá trình đã kiểm chứng. Thứ tự dùng hiện trong Analysis Setup và Report. | Người dùng; Minitab giả định worksheet theo thứ tự thu thập |
| D4 | RawData.xlsx **giữ nguyên là dữ liệu thô**. Operator/Slot được cấu hình **trên màn hình app**. | Người dùng |
| D5 | **Variable GRR:** mặc định 1 appraiser, mỗi nest/slot một kết quả riêng. Phân biệt *One Appraiser* và *Crossed* (mục 5.2). Không tự xem Nest/Slot là Operator; nếu người dùng chủ động chọn "Nest as Operator" thì hiển thị giải thích ý nghĩa thống kê và ghi vào Report. **Không** làm Expanded và Nested ở phiên bản đầu. | Người dùng; WI 8.7.2, bảng 8.7.2; Minitab |
| D6 | Cho phép **báo cáo từng phần**, ghi rõ "Included n of m items". | Người dùng |
| D7 | Gage name, Date of study, Reported by **bắt buộc khi Generate Report**, không bắt buộc khi Run Analysis. | Quy tắc riêng của DataMapperX |
| D8 | Kết quả cũ (stale) có thể giữ để tham khảo nhưng **không được xuất thành báo cáo hiện hành**. | Quy tắc riêng, chặt hơn Minitab (WI 8.12.2) |
| D9 | Analysis Setup phân biệt hai mục đích: **MSA** (Variable Gage R&R) và **Process Capability** (Cp/Cpk, Pp/Ppk). | Người dùng |
| D10 | Không tuyên bố "Minitab-equivalent" khi chưa có Golden Test. Trạng thái từng phương pháp: `Pending Minitab Verification` hoặc `Minitab Verified`. Thiếu output Minitab không cản việc refactor kiến trúc ở Giai đoạn 0, nhưng **không được đổi công thức chưa kiểm chứng**. | Người dùng; WI 8.1.4, 8.7.7 |
| D11 | **Quick Analysis:** chọn dữ liệu → chọn phương pháp → Run Analysis là đủ. Export Excel của Data Mapping hoạt động độc lập; Advanced Analysis, Preview Report, Generate PDF/Excel đều là tùy chọn. | Người dùng |
| D12 | **Ba thành phần độc lập:** *Statistical Metrics* (Cpk, Ppk, %SV/Tol, %Study Var, NDC…); *Evaluation Status* (PASS / CONDITIONAL PASS / FAIL / N/A theo tiêu chí); *Validation Status* (điều kiện phân tích đã kiểm chứng, còn cảnh báo, hay chưa xác nhận). `Pending Minitab Verification` / `Minitab Verified` là trạng thái kiểm chứng **phương pháp tính**, không thay thế Validation Status của từng dataset. Đổi tiêu chí hoặc xác nhận không gọi lại `compute()`. Kết quả và báo cáo lưu tiêu chí, phiên bản tiêu chí và trạng thái xác nhận đã dùng. | Người dùng |
| D13 | **Fingerprint thống kê** (dữ liệu, thứ tự, mapping, study design, limits, statistical options liên quan) ổn định giữa các tiến trình, không phụ thuộc object ID hay đường dẫn. **Provenance** (đường dẫn, file nguồn, sheet, dòng, timestamp) tách riêng. Hai nguồn A/B cùng dữ liệu và cấu hình thống kê phải cho metrics tương đương dù provenance khác. | Người dùng |
| D14 | Giai đoạn 0 được duyệt đúng phạm vi mục 10, với điều kiện mục 15. Không tự mở rộng sang Giai đoạn 1; nếu regression thất bại hoặc cần đổi công thức thì báo cáo, không tự điều chỉnh hành vi cũ. | Người dùng |

## 2. Hiện trạng và vấn đề (đã kiểm tra trong source)

| Vấn đề | Vị trí | Hệ quả |
|---|---|---|
| Validation chỉ có trong trang review, cần scan và chọn component | `main_window.py:603`, `:460` | Không dùng được khi khởi động |
| Panel giữ tham chiếu sống tới `scan_result.grouped` | `main_window.py:1090` | Không có snapshot |
| Duplicate dialog sửa trực tiếp `LogRecord` dùng chung | `duplicate_dialog.py:92` | Dữ liệu đổi ngầm |
| Nhận biết dataset đổi bằng `id(grouped)`; rescan xóa im lặng mapping | `validation.py:210` | `id()` có thể bị dùng lại |
| Đổi số thập phân hoặc bộ lọc item gọi `invalidate()` | `validation.py:78` | Kết quả bị xóa chỉ vì đổi hiển thị |
| `expected_repeats` lấy từ ô "Files per sample" của Data Mapping | `main_window.py:1090` | Thiết kế study nằm sai module |
| Thứ tự `grouped` là thứ tự path; RawData sắp theo SN | `scanner.py:113`, `exporter.py:61` | Cùng dữ liệu, thứ tự khác, Cpk khác |
| RawData.xlsx không ghi tên file, Trial, Operator, Slot, Timestamp; limits chỉ lấy file đầu | `exporter.py:77` | Import lại mất ngữ nghĩa |
| `analyze()` chấm luôn acceptance | `engine.py` | Đổi customer buộc tính lại thống kê |

Điểm tách tốt đã có: `normalize_records` là adapter duy nhất từ `LogRecord` sang `Observation`; engine, `stat_reports`, `stat_charts` không phụ thuộc Tk hay `LogRecord`. Các vấn đề cần sửa ở lớp giao diện (`id(grouped)`, số thập phân, `expected_repeats`) thuộc Giai đoạn 1, không thuộc Giai đoạn 0.

## 3. Kiến trúc đích: Dataset → Study → Statistics → Evaluation → Results → Report

```
Data Mapping ─(snapshot)─┐
Import (xlsx/csv) ───────┼─► Dataset (bất biến, có fingerprint)
                         │
Study ───────────────────┘
  ├─ Dataset + mapping + study design + thứ tự dữ liệu
  ├─ Statistical options (phương pháp, α, k, within sigma, expected repeats, limits)
  │        │
  │        ▼  compute()           ← chỉ phụ thuộc các mục ở trên
  ├─ Statistics (metrics, ANOVA, sigma, issues)
  │        │
  │        ▼  evaluate()          ← chạy lại độc lập
  ├─ Evaluation (customer criteria, xác nhận điều kiện) → PASS / CONDITIONAL / FAIL / N/A
  ├─ Result sets (Statistics + Evaluation + fingerprint đầu vào + trạng thái kiểm chứng)
  ├─ Study Info (metadata)
  └─ ReportSpec (item nào, mục nào, thứ tự, comment)
```

- **Study** là đối tượng trạng thái độc lập; các tab chỉ là view.
- **Dataset** là bản chụp bất biến, chỉ chứa các Test Item được chọn. Mỗi quan sát có `source` duy nhất (file, hoặc sheet + dòng) và `worksheet_index`. Có thể có `acquisition_key` (timestamp hoặc run order) kèm cờ `order_basis`. Có fingerprint (SHA-256 trên biểu diễn chuẩn hóa, ổn định giữa các lần chạy và nền tảng, không dùng `id()` hay `hash()`).
- **Tách `analyze`** thành `compute()` (Statistics) và `evaluate()` (Evaluation). `analyze()` hiện tại giữ lại làm hàm gộp với đầu ra **giống hệt**.
- **Quy tắc stale:**

| Thay đổi | Ảnh hưởng |
|---|---|
| Dữ liệu, mapping, study design, thứ tự dữ liệu, statistical options, limits | Statistics bị stale, kéo theo Evaluation |
| Customer criteria, chỉ số quyết định, xác nhận điều kiện | Chỉ chạy lại Evaluation, **không đổi** metrics |
| Study Info, số thập phân, lựa chọn/thứ tự nội dung báo cáo, bố cục, theme | Không stale |

- Kết quả stale được giữ lại để tham khảo, hiển thị banner, và **không xuất** thành báo cáo hiện hành. Có thể giữ kết quả cũ và tạo bộ kết quả mới (kiểu "Create new results" của Minitab).
- Data Mapping thay đổi sau snapshot **không** đổi Study; chỉ hiện gợi ý không chặn: "Data Mapping đã thay đổi — [Refresh from Data Mapping]".

### Ba thành phần độc lập

| Thành phần | Nội dung | Phụ thuộc vào | Lưu trong |
|---|---|---|---|
| **Statistical Metrics** | Cpk, Ppk, %SV/Tol, %Study Var, NDC, sigma, ANOVA… | Dataset, mapping, design, statistical options | `StatisticsResult` |
| **Evaluation Status** | PASS / CONDITIONAL PASS / FAIL / N/A | Metrics + tiêu chí (+ trạng thái xác nhận khi áp dụng) | `EvaluationRecord` |
| **Validation Status** | Các điều kiện phân tích: mức (Information/Warning/Critical), đã xác nhận chưa, đã kiểm chứng chưa | Dữ liệu và kết quả phát hiện điều kiện | `ValidationRecord` |
| *(thuộc tính phương pháp)* | `Pending Minitab Verification` / `Minitab Verified` | Phương pháp tính, không phụ thuộc dataset | Sổ kiểm chứng (mục 12) |

`EvaluationRecord` lưu: tiêu chí đã dùng (bản sao bất biến), **phiên bản tiêu chí** (hash nội dung, ví dụ `criteria-v1:<16 ký tự>`), trạng thái xác nhận. Kết quả và báo cáo giữ nguyên các thông tin này để khi tiêu chí đổi sau đó vẫn truy được báo cáo cũ đã chấm theo tiêu chí nào.

### Fingerprint và provenance

**Fingerprint thống kê** (`v1:` + SHA-256) tính trên biểu diễn chuẩn hóa:
- Với mỗi Test Item (sắp theo tên), chuỗi các quan sát theo đúng thứ tự: Sample ID, giá trị, LSL, USL, Trial, Tester, Operator, Slot, Unit, Subgroup. Thứ tự tương đối giữa các quan sát cùng item được giữ; thứ tự giữa các item khác nhau không ảnh hưởng.
- Giá trị số được chuẩn hóa theo giá trị số học (`"1.230"` và `1.23` cho cùng kết quả); giá trị không phải số giữ nguyên dạng chữ (vì tạo lỗi xác thực).
- Định danh được `strip()` như engine đang làm.
- `source` được thay bằng chỉ số lần xuất hiện đầu tiên: vẫn giữ cấu trúc "cùng nguồn xuất hiện hai lần" (engine báo lỗi trùng nguồn) nhưng không phụ thuộc văn bản đường dẫn.

**Không** thuộc fingerprint thống kê: đường dẫn/file/sheet/dòng nguồn, timestamp, `order_basis`, mô tả nguồn. Các thông tin này thuộc **provenance** (có hash riêng).

Fingerprint toàn bộ đầu vào của một ResultSet gồm: fingerprint dataset, mapping, study design và statistical options liên quan. Mỗi thành phần có hash riêng để báo lý do stale.

## 4. Nguồn dữ liệu

**A. Use Data Mapping results:** tạo snapshot trong bộ nhớ (không cần xuất Excel), không sửa `LogRecord`. Vô hiệu hóa nếu chưa có mapping.

**B. Import raw data:**
- *MVP:* (1) nhận diện RawData.xlsx của DataMapperX; (2) template long-format của DataMapperX.
- *Sau:* wizard xlsx/csv tổng quát (sheet, dòng tiêu đề, vùng dữ liệu, wide→long, locale dấu thập phân). **Không tự đoán Trial, Operator, Slot**: chỉ gợi ý và bắt xác nhận.

**Thứ tự dữ liệu của hai nguồn:**
- Mặc định là **Worksheet Order**, nhãn rõ "thứ tự dòng dữ liệu, không phải thứ tự thu thập". Với nguồn A, Worksheet Order là thứ tự dòng của RawData; với nguồn B là thứ tự dòng của file.
- Acquisition Order chỉ có khi người dùng khai báo cột/giá trị timestamp hoặc run order mà họ xác nhận là đáng tin cậy. Hiện chương trình chưa tự lấy timestamp từ logfile; chỉ gán thủ công từng file.
- Cùng dữ liệu, mapping, design, thứ tự và options phải cho cùng kết quả giữa A và B.

**Quy tắc đọc RawData.xlsx:**
- Sheet "Raw Data"; hàng 1 gồm STT, SN, các component; một cột trống; rồi NAME/MIN/MAX/UNIT. Dùng cột trống làm ranh giới, không coi NAME/MIN/MAX/UNIT là measurement.
- Ghép limits/unit theo tên component: khớp chính xác trước (giữ nguyên khoảng trắng kép), rồi khớp chuẩn hóa kèm cảnh báo.
- SN đọc dạng text (giữ số 0 đầu). STT **không** làm Trial. Ô rỗng là thiếu dữ liệu.
- Mỗi quan sát có `source` duy nhất (sheet + dòng) để không bị báo trùng nguồn sai.
- Số chỉ nhận dạng dấu chấm; CSV có dấu phẩy thập phân hoặc ngăn cách hàng nghìn thì hiện số ô bị từ chối và cho chọn locale.

**RawData.xlsx không có** (nên phải cấu hình trên màn hình): tên file nguồn, Trial, Operator, Tester, Slot, Timestamp, limits riêng từng file, lựa chọn duplicate.

## 5. Study purpose và Study design

### 5.1 Study purpose

| Mục đích | Phương pháp | Câu hỏi trả lời |
|---|---|---|
| **MSA** | Variable Gage R&R | Hệ thống đo có đủ tốt không? |
| **Process Capability** | Cp/Cpk, Pp/Ppk | Quá trình sản xuất có đạt spec không? |

Mỗi mục đích có vai trò dữ liệu bắt buộc, cảnh báo và tiêu chí riêng. Dữ liệu GRR (nhiều lần đo cùng SN) không được mặc định dùng để kết luận năng lực quá trình.

### 5.2 Variable GRR: One Appraiser và Crossed

**One Appraiser (mặc định)**
- Đánh giá Repeatability và Part-to-Part.
- **Không** ước lượng Reproducibility giữa các operator; báo cáo ghi "One-appraiser study: repeatability only" và không trình bày như nghiên cứu GRR nhiều operator.
- Vẫn tính %Study Var, %SV/Tol và NDC khi dữ liệu và phương pháp cho phép.
- Mỗi nest/slot cho một kết quả riêng.

**Crossed GRR**
- Dùng khi nhiều operator cùng đo các part tương ứng, có lặp phép đo theo thiết kế hợp lệ.
- Kiểm tra đủ tổ hợp Part × Operator, cân bằng và số lần lặp (theo mô hình đang hỗ trợ).
- Không tự động xem Nest/Slot là Operator.
- **Nest as Operator** là lựa chọn chủ động. Khi chọn, app giải thích: "Reproducibility lúc này phản ánh chênh lệch giữa các nest, không phải giữa người đo; kết luận áp dụng cho fixture như một khối, không áp dụng cho từng nest" (WI 8.7.2 cho phép, nhưng WI cũng yêu cầu duyệt từng nest riêng). Lựa chọn này được ghi vào Report.

| Thiết lập | Mặc định | Đổi khi |
|---|---|---|
| Số appraiser | 1 | Nhiều người đo: khai "n operators", đặt tên |
| Nest/Slot | Mỗi nest riêng | "Nest as Operator" (chủ động, có giải thích, ghi vào Report) |
| Người + nest | Người là Operator, mỗi nest riêng | Gộp một mô hình thì cần Expanded (không có ở phiên bản đầu) |

**Khi file không có cột Operator:** khai "n operators × t trials mỗi sample" và thứ tự dòng của một SN (theo từng operator hoặc theo từng lượt). App kiểm tra mỗi SN có đúng n × t dòng, hiện bảng gán trong preview để xác nhận. Cách này dựa vào thứ tự dòng nên **bắt xác nhận, không đoán**.

**Trial** là tùy chọn, suy ra từ thứ tự dòng trong từng (Sample × Operator) và hiển thị để xác nhận (Minitab không có cột Trial).

**Cảnh báo thiết kế** (theo Minitab và WI 8.7.4): ít hơn 10 sample; số operator/lần lặp thấp hơn bảng 8.7.4; ít hơn 2 lần lặp là lỗi; thiếu cặp Sample × Operator là lỗi vì không phải crossed.

### 5.3 Process Capability: điều kiện và mức cảnh báo

Capability chạy trên toàn bộ N phép đo. Người dùng **không phải xác nhận mọi cảnh báo**; mỗi điều kiện có một mức:

| Mức | Ví dụ | Hành vi |
|---|---|---|
| **Information** | N < 100 (Minitab khuyên ≥ 100) | Hiển thị khuyến nghị. Không cần xác nhận; không ảnh hưởng Evaluation. |
| **Warning** | Thiếu Acquisition Order đáng tin cậy (đang dùng Worksheet Order); có phép đo lặp cùng SN | Cho phép phân tích và xem metrics. Phải **xác nhận điều kiện áp dụng** trước khi dùng kết quả để đánh giá; trước đó hiển thị "Not evaluated: conditions unconfirmed". |
| **Critical** | Dữ liệu không hợp lệ hoặc không thể tính đúng (σ bằng 0 hoặc ngoài miền số, giá trị thiếu/không hợp lệ, đơn vị xung đột, giới hạn mâu thuẫn) | **Không bao giờ** ra PASS/FAIL; không thể xác nhận để vượt qua. |

**Xác nhận (acknowledgement) khác kiểm chứng (verification).** Mỗi điều kiện có hai trạng thái riêng:
- `acknowledged`: người dùng đã đọc và chấp nhận rủi ro (ghi ai, khi nào, nội dung đã xem).
- `verification`: `NOT_ASSESSED` / `MET` / `NOT_MET`, kèm bằng chứng (tên kiểm định, giá trị thống kê).

Xác nhận **không bao giờ** đổi `verification` thành `MET`. Validation Status tổng hợp có bốn mức: `INVALID` (có Critical), `UNCONFIRMED` (còn Warning chưa xác nhận), `ACKNOWLEDGED` (đã xác nhận nhưng chưa kiểm chứng), `VERIFIED` (mọi điều kiện Warning trở lên đã `MET`). Báo cáo ghi rõ "acknowledged, not verified" khi áp dụng.

**Ổn định quá trình và phân phối chuẩn.** Minitab nêu rõ: dữ liệu nên thu theo subgroup hợp lý, quy trình "must be stable and in control" (kiểm tra bằng Xbar-S hoặc Capability Sixpack), dữ liệu "should follow a normal distribution" (nếu không thì Box-Cox, Johnson hoặc Nonnormal). Capability Evaluation phải tính đến hai giả định này. Giai đoạn 0 chỉ **khai báo hai điều kiện** `process_stability` và `normality` (mức Warning, `verification = NOT_ASSESSED`). Không cài đặt kiểm định mới trong Giai đoạn 0, vì kiểm định thống kê mới chưa thể kiểm chứng với Minitab. Chừng nào chưa có kiểm định, Validation Status của Capability không thể đạt `VERIFIED`, và báo cáo ghi rõ.

Xác nhận chỉ ảnh hưởng Evaluation, không tính lại Statistics. Giai đoạn 0 **không** có giao diện xác nhận; chỉ có cấu trúc dữ liệu (mục 10).

## 6. Quy tắc thống kê

**Gage R&R:** one-way khi 1 appraiser; crossed khi ≥ 2 operator trong cùng item/tester/slot (α loại interaction 0.05, Study Var 6). Không gộp tester/slot khác nhau; không suy reproducibility khi dữ liệu thiếu điều kiện. One-way không bao giờ báo Reproducibility như đã được ước lượng. %SV/Tol dùng Process tolerance = USL − LSL.

**Capability:**
- Hiển thị Cpk và Ppk (và Cp, Pp) khi đủ điều kiện tính. Với một giới hạn: Cpk/Ppk một phía có nhãn "upper only" hoặc "lower only" (hoặc CPU/CPL); Cp/Pp là N/A.
- Tiêu chí (chỉ số quyết định và ngưỡng) cấu hình theo Customer / Study Purpose / WI. Mặc định cho Process Capability thông thường là Cpk > 1.33. WI 8.4.1 dùng Ppk > 1.33 khi đổi script, nên cấu hình "script change" dùng Ppk.
- Thứ tự dữ liệu quyết định Moving Range và Within Sigma, nên quyết định Cp/Cpk. Pp/Ppk (độ lệch chuẩn tổng thể) không phụ thuộc thứ tự.
- Subgroup khai báo bằng Subgroup ID; các dòng cùng ID phải liền kề (theo Minitab). Không tự coi các lần đo lặp cùng SN là rational subgroup.
- Mô phỏng 30 SN × 3 lần, cùng dữ liệu: Cpk 5.97 (xếp từng SN), 2.14 (xếp theo lượt), 42.27 (subgroup = SN); Ppk không đổi 2.05. Đây là lý do thứ tự phải hiển thị và có cảnh báo.
- Cảnh báo thông tin khi N < 100 (hiện đang cảnh báo ở N < 30).

**Chấm tiêu chí Gage R&R** (`customers.py` đã có): kết quả là xấu nhất trong các metric đang áp dụng; metric không áp dụng chỉ thông tin và có cờ Review. Đổi tiêu chí không đổi metrics.

**Gage resolution (discrimination)** là trường tùy chọn trong Study Info, tách khỏi Process tolerance. WI 8.3.4: "the discrimination of the measurement equipment should be at least 1/10 of the specification defined and 1/20 is preferred." Hiểu là bước đo nhỏ nhất không lớn hơn một phần mười dung sai:
- **Resolution ≤ (USL − LSL) / 10** (yêu cầu theo WI).
- **Resolution ≤ (USL − LSL) / 20** (ưu tiên, tiêu chí chặt hơn).
- Ví dụ dung sai 10: resolution ≤ 1.0 là đạt yêu cầu; ≤ 0.5 là mức ưu tiên.
- Chỉ áp dụng khi có đủ hai giới hạn; một phía hoặc thiếu giới hạn thì N/A. Mặc định là cảnh báo, không chặn. Hai ngưỡng cấu hình được vì WI không nêu yêu cầu riêng của khách hàng. Cách hiểu "at least 1/10" cần TE xác nhận.

## 7. Giao diện

Hai workspace cấp cao: **Data Mapping** | **Validation & Reports**. Validation mở được ngay khi khởi động. Export Excel của Data Mapping luôn độc lập; lỗi hay thiếu dữ liệu ở Validation không bao giờ chặn Export Excel.

Bốn tab, ưu tiên **Quick Analysis**:

| Tab | Nội dung |
|---|---|
| **Data** | Chọn nguồn A/B; thẻ snapshot (samples, measurements, items, xung đột limits, hash); preview; xác nhận mapping |
| **Analysis Setup** | Study purpose (MSA / Process Capability); phương pháp; chỉ các vai trò bắt buộc; Study design; thứ tự dữ liệu; dòng tóm tắt; Options thu gọn; Customer |
| **Results** | Banner stale; ba chỉ số ưu tiên; chi tiết thu gọn |
| **Report** | Study Info; danh sách nội dung và thứ tự; comment; preview; Generate |

**Quick Analysis:** chọn dữ liệu, chọn phương pháp, Run Analysis. Study Info, Customer chi tiết và Options không bắt buộc để chạy.

**Results cho Variable GRR** ưu tiên ba chỉ số: **%SV/Tol (%Tolerance)**, **%Study Variation**, **NDC**. ANOVA, variance components, biểu đồ, R/Xbar và thông số nâng cao nằm trong phần chi tiết.

**About / Calculation Details:** nút xem công thức, dữ liệu đã dùng, phương pháp, giả định, tiêu chí đánh giá, thứ tự dữ liệu, trạng thái kiểm chứng Minitab.

Banner stale: "Data changed — rerun analysis", kèm [Update results] [Giữ và tạo kết quả mới]. Tab bật dần theo tiến trình. Preview báo cáo là bản có cấu trúc (checklist + trang tóm tắt) cộng nút mở PDF vừa tạo, vì Tk không có trình xem PDF.

## 8. Báo cáo

**Study Info:** bắt buộc khi Generate: Gage name, Date of study, Reported by. Tùy chọn: Misc/Comments, Gage resolution, Equipment/Fixture ID, Product, Workcell. "Customer" **là** customer criteria đang chọn. Date of study là ngày thực hiện nghiên cứu, khác ngày tạo báo cáo. Sửa Study Info chỉ cập nhật báo cáo.

**PDF:** Study Info; nguồn dữ liệu và thiết lập (study purpose, design, thứ tự dữ liệu và loại thứ tự, Nest as Operator nếu có, xác nhận điều kiện capability); summary và tiêu chí; chi tiết từng item và biểu đồ; methodology; trạng thái kiểm chứng Minitab; phụ lục liệt kê item không đưa vào.

**Excel:** Study Info, Summary, Item sheets, Raw Data (các quan sát đã dùng), Methodology.

**Một phần:** mọi trang ghi "Included n of m items"; tiêu đề đánh dấu partial.

**Provenance** (WI 8.12.2): danh sách file nguồn, số lượng, hash dataset.

PDF và Excel dùng cùng một bộ kết quả; %Contribution, %Study Var, %SV/Tol tính một lần trong engine. Báo cáo ghi tiêu chí đã dùng, phiên bản tiêu chí, trạng thái xác nhận và Validation Status; trạng thái kiểm chứng phương pháp được ghi riêng. Báo cáo ghi trạng thái từng phương pháp: `Pending Minitab Verification` hoặc `Minitab Verified`; không dùng cụm "tương đương Minitab" khi chưa có Golden Test.

## 9. Phân kỳ

**Giai đoạn 0, nền kiến trúc** (mục 10): Dataset bất biến + fingerprint ổn định, Study + Result Set, stale detection, tách Statistics/Evaluation, dữ liệu thứ tự, giữ `analyze()`. **Không đổi** giao diện, Data Mapping, Export Excel, công thức thống kê. Viết regression test **trước** khi refactor.

**Giai đoạn 1:** workspace độc lập; nguồn A từ snapshot; Study purpose; Study design; Study Info; Quick Analysis và ba chỉ số; chặn xuất khi stale; xác nhận điều kiện capability; báo cáo từng phần; sửa `id(grouped)`, số thập phân, `expected_repeats`.

**Giai đoạn 2:** nguồn B: importer RawData.xlsx; template long-format; "Create study worksheet" kiểu Minitab.

**Giai đoạn 3:** wizard xlsx/csv tổng quát; `@folder`, regex, gán hàng loạt; tiêu chí capability theo customer.

**Giai đoạn 4:** Save/Open Study; report templates; mapping presets; %SV/Tol một phía; historical SD.

| Phân loại | Hạng mục |
|---|---|
| Must | Giai đoạn 0, Giai đoạn 1, importer RawData.xlsx, Golden Test infrastructure |
| Should | Template + Create study worksheet, wizard tổng quát, cảnh báo thiết kế, %SV/Tol một phía, tiêu chí capability theo customer |
| Later | Save/Open Study, report templates, mapping presets, estimator within sigma khác, Expanded/Nested (không thuộc phạm vi hiện tại) |

## 10. Phạm vi triển khai Giai đoạn 0

Thứ tự thực hiện:
1. **Baseline trước:** viết regression test trên code **hiện tại** và chạy xanh (mục 11).
2. Refactor thêm kiểu mới và tách hàm.
3. Chạy lại baseline: đầu ra phải giống hệt từng bit.

| Nhóm | File / module | Nội dung |
|---|---|---|
| **Thêm mới** | `statistics/dataset.py` | `Dataset` bất biến; `snapshot_from_records()` (đọc `LogRecord`, không sửa); metadata thứ tự (`worksheet_index`, `acquisition_key`, `order_basis`); fingerprint SHA-256 chuẩn hóa |
| | `statistics/study.py` | `StatisticalOptions`, `Study`, `ResultSet`, lý do stale theo từng thành phần, fingerprint đầu vào, `StudyInfo`, sổ kiểm chứng phương pháp (`MethodVerification`) |
| | `statistics/evaluation.py` | `evaluate()` dùng lại `acceptance.py` và `customers.py`; `EvaluationRecord` (tiêu chí, phiên bản tiêu chí, xác nhận); cấu trúc Validation Status (`Severity`, `Condition`, `Acknowledgement`, `Verification`, `ValidationRecord`) |
| **Sửa, không đổi hành vi** | `statistics/engine.py` | Tách `compute()` và `evaluate()`; `analyze()` = gộp, đầu ra giống hệt |
| | `statistics/models.py` | Thêm `StatisticsResult` (kết quả trước Evaluation) và phân loại trường cấu hình (`STATISTICAL_FIELDS`, `EVALUATION_FIELDS`, `DISPLAY_FIELDS`, `statistical_config`); giữ nguyên `AnalysisConfig`, `AnalysisResult`, `Observation` |
| | `statistics/__init__.py` | Export |
| **Thêm test** | `tests/test_regression_baseline.py`, `tests/baseline_support.py`, `tests/make_baseline.py` + `tests/fixtures/baseline/*.json` | Khóa đầu ra `analyze()` |
| | `tests/test_export_regression.py` | Khóa RawData.xlsx |
| | `tests/test_dataset.py`, `tests/test_study.py` | Fingerprint, thứ tự, stale, chỉ chạy Evaluation |
| **Giữ nguyên (không sửa)** | `ui/main_window.py`, `ui/validation.py`, `ui/duplicate_dialog.py`, `scanner.py`, `exporter.py`, `profiles.py`, `sampling.py`, `xlsx.py`, `grr.py` (pre-check), `settings.py` | Data Mapping, Export, UI hiện tại |
| | `stat_reports.py`, `stat_charts.py`, `statistics/capability.py`, `statistics/grr.py`, `statistics/crossed.py`, `statistics/numeric.py`, `statistics/formulas.py`, `statistics/customers.py`, `statistics/normalize.py` | Công thức, báo cáo, thứ tự hiện tại |

Ghi chú:
- `Study` và `Dataset` ở Giai đoạn 0 chưa nối vào giao diện; chỉ được dùng trong test và làm API cho Giai đoạn 1.
- `normalize_records` giữ nguyên thứ tự hiện tại (thứ tự scan) cho panel hiện có. Thứ tự Worksheet Order của Dataset mới được xây riêng trong `snapshot_from_records()`. Hai thứ tự có thể khác nhau; sự khác biệt được tài liệu hóa trong baseline.
- Định nghĩa chi tiết các kiểu được chốt trong lúc triển khai Giai đoạn 0, không đổi các trường của `AnalysisResult`.
- **Baseline lấy từ trạng thái trên đĩa ngày 30/10/2026**, đã bao gồm hàm `ndc_from_variances` (trong `statistics/numeric.py`, dùng ở `statistics/grr.py` và `grr.py` pre-check) cùng các test liên quan do bên ngoài thêm trước khi Giai đoạn 0 bắt đầu. Phần này không do Giai đoạn 0 thay đổi.
- `statistics/validation.py`, `statistics/acceptance.py`, `statistics/customers.py` giữ nguyên; các hàm kiểm tra cấu hình mới đặt trong `study.py` và `evaluation.py`.

## 11. Tiêu chí chấp nhận và nhóm kiểm thử

**Chấp nhận chung:**
- AC1: Validation mở và chạy được khi khởi động mà không scan.
- AC2: Cùng dữ liệu, mapping, study design, thứ tự và statistical options cho cùng `metrics` giữa nguồn A và B (sai số tương đối ≤ 1e-12).
- AC3: Sau khi snapshot, rescan, bỏ component, resolve duplicate không đổi Study.
- AC4: Đổi dữ liệu, mapping, design, thứ tự, options hoặc limits thì kết quả stale; đổi Study Info, số thập phân, nội dung báo cáo thì không; đổi customer chỉ chấm lại.
- AC5: Generate Report kiểm tra đủ ba trường bắt buộc; Date of study tách khỏi ngày tạo.
- AC6: PDF và Excel cùng giá trị; báo cáo từng phần ghi "Included n of m".
- AC7: Mặc định One Appraiser, nest riêng; Crossed chỉ khi khai ≥ 2 operator; thiếu Part × Operator thì báo lỗi rõ.
- AC8: Mọi kết quả undefined là N/A kèm giải thích; NDC là số nguyên.
- AC9: Không được suy ra Acquisition Order từ SN đã sắp xếp hoặc từ thứ tự RawData.xlsx.
- AC10: Capability dùng dữ liệu đo lặp phải có cảnh báo phù hợp.
- AC11: Không tự động chấm PASS/FAIL cho Capability khi điều kiện phân tích chưa được xác nhận; metrics vẫn xem được ở chế độ preview.
- AC12: One-way GRR không báo cáo Reproducibility như đã được ước lượng.
- AC13: Thay đổi customer criteria không đổi statistical metrics và không chạy lại Statistics.
- AC14: Chỉ đánh dấu `Minitab Verified` sau khi qua Golden Test; trước đó là `Pending Minitab Verification`.
- AC15: Regression test chứng minh Data Mapping và Export Excel cũ không bị ảnh hưởng.
- AC16: Một giới hạn spec: Cp/Pp là N/A, Cpk/Ppk có nhãn theo phía; không tạo giá trị hai phía.
- AC17: "Nest as Operator" hiển thị giải thích và được ghi vào Report; không bao giờ tự bật.
- AC18: Quy tắc Gage Resolution đúng hướng ở biên: ≤ (USL − LSL)/10 đạt; ≤ (USL − LSL)/20 là mức ưu tiên.
- AC19: Kết quả stale không xuất được thành báo cáo hiện hành.
- AC20: Export Excel của Data Mapping chạy được mà không cần Validation; lỗi Validation không chặn Export.
- AC21: Statistical Metrics, Evaluation Status và Validation Status độc lập: đổi tiêu chí hoặc xác nhận không đổi metrics và không gọi `compute()`.
- AC22: Xác nhận không bao giờ đổi `verification` thành `MET`; Validation Status không đạt `VERIFIED` chỉ nhờ xác nhận.
- AC23: Điều kiện Critical không bao giờ cho PASS/FAIL, kể cả khi đã xác nhận.
- AC24: Kết quả và báo cáo lưu tiêu chí đã dùng, phiên bản tiêu chí và trạng thái xác nhận; hai tiêu chí khác nhau cho hai phiên bản khác nhau.
- AC25: Fingerprint thống kê không phụ thuộc provenance (đường dẫn, file, sheet, dòng, timestamp); nguồn A/B cùng dữ liệu cho metrics bằng nhau.
- AC26: `Pending Minitab Verification` / `Minitab Verified` là thuộc tính phương pháp và không thay thế Validation Status của dataset.

**Tiêu chí thoát Giai đoạn 0 (trước khi sang Giai đoạn 1):**
- P0-1: Baseline regression chạy xanh trước và sau refactor; đầu ra `analyze()` (metrics ở độ chính xác đầy đủ, status, issues theo thứ tự, details) giống hệt.
- P0-2: Test khóa RawData.xlsx (giá trị, kiểu ô, number format, thứ tự dòng, bảng limits) xanh; không có thay đổi trong `exporter.py`, `scanner.py`, `ui/`.
- P0-3: Fingerprint ổn định giữa các lần chạy tiến trình khác nhau, khác nhau khi đổi dữ liệu hoặc thứ tự, không đổi khi chỉ đổi trường không thuộc fingerprint.
- P0-4: Ma trận stale (mục 3) đúng cho từng loại thay đổi, kể cả các thay đổi không gây stale.
- P0-5: Đường chạy chỉ Evaluation không gọi `compute()` (kiểm bằng spy) và metrics bằng nhau từng bit.
- P0-6: Toàn bộ test hiện có chạy không cần sửa; ruff sạch; smoke test (`--smoke-test`) pass.
- P0-7: Không thay đổi công thức thống kê (không có diff trong các file thuộc nhóm "giữ nguyên").

**Nhóm test:**
- *Regression baseline:* one-way, crossed (giữ và bỏ interaction), capability individuals, pooled, criteria; lưu giá trị ở độ chính xác đầy đủ. Đây là **baseline hành vi hiện tại, không phải kiểm chứng Minitab**.
- *Round-trip RawData (Giai đoạn 2):* SN số 0 đầu, giá trị, ô trống, limits, tên có khoảng trắng kép, bảng limits không bị đọc thành measurement, STT không thành Trial.
- *Tương đương nguồn A/B*, *cô lập snapshot*, *ma trận stale*.
- *Study design:* pattern gán operator, thiếu ô, không cân bằng, Nest as Operator.
- *Capability:* thứ tự, đo lặp cùng SN, xác nhận điều kiện, một phía, N < 100.
- *Báo cáo:* nhất quán PDF/Excel, ba trường bắt buộc, một phần, provenance, trạng thái kiểm chứng, chống formula injection.
- *Import (Giai đoạn 2–3):* encoding, delimiter, dấu thập phân, công thức, ô gộp, hàng ẩn, số lưu dạng text, hủy giữa chừng, 50k dòng.
- *UI (Giai đoạn 1):* khởi động không scan, khung 1000×680, theme sáng/tối.

## 12. Kiểm chứng Minitab (Golden Test)

**Sổ kiểm chứng:**

| Phương pháp | Tham chiếu hiện có | Trạng thái |
|---|---|---|
| One-way GRR | Báo cáo Minitab (PDF) của nghiên cứu FT, độ chính xác in ra 7 chữ số thập phân, không in NDC | Đã so một phần ở độ chính xác in; `Pending Minitab Verification` |
| Crossed GRR, interaction bị loại | Chưa có | `Pending Minitab Verification` |
| Crossed GRR, interaction được giữ | Chưa có | `Pending Minitab Verification` |
| Capability, Individuals (MR) | Chưa có (báo cáo Cpk của ICT không kèm dữ liệu gốc) | `Pending Minitab Verification` |
| Capability, pooled Subgroup ID | Chưa có | `Pending Minitab Verification` |
| Giới hạn biểu đồ R/Xbar | In ra 6 chữ số thập phân | Đã so một phần; `Pending Minitab Verification` |

**Quy trình:** với mỗi trường hợp, người dùng xuất từ Minitab (a) dữ liệu đầu vào, (b) Session output, (c) cột lưu trữ nếu có. Fixtures đặt dưới `tests/fixtures/minitab/<case>/` (dữ liệu, output Minitab, giá trị mong đợi, ghi chú tùy chọn và thứ tự dữ liệu).

**So sánh các giá trị trung gian, không chỉ PASS/FAIL hay số đã làm tròn:**
- GRR: SS, DF, MS, F, p của từng nguồn; variance components; sigma; Study Var; %Contribution, %Study Var, %Tolerance; NDC.
- Capability: trung bình; MRbar và hằng số d2; StDev(within) và StDev(overall); Pp, PPL, PPU, Ppk; Cp, CPL, CPU, Cpk.
- Dung sai: nửa đơn vị chữ số cuối cùng Minitab in ra (hoặc 1e-9 tương đối nếu có đủ chữ số).

Một phương pháp chỉ được đánh dấu `Minitab Verified` khi mọi trường hợp của nó qua. Cho đến lúc đó, báo cáo và About ghi `Pending Minitab Verification`.

## 13. Rủi ro và điểm chưa kiểm chứng

- **Phụ thuộc output Minitab:** chưa có đủ output để đánh dấu bất kỳ phương pháp nào là `Minitab Verified`. Không thay công thức khi chưa kiểm chứng.
- **Cách macro GRR trong WI 8.9 tính Cpk chưa biết.** Cpk của app có thể không bằng số của macro nếu macro dùng thứ tự hoặc subgroup khác. Cần output của macro.
- **Acquisition Order:** chương trình chưa lấy timestamp từ logfile; hiện chỉ gán tay từng file. Nếu ít dữ liệu có thứ tự thu thập đáng tin cậy, phần lớn capability sẽ ở chế độ cảnh báo.
- **WI 8.3.4** chưa nêu yêu cầu riêng của khách hàng cho Gage Resolution; cách hiểu "at least 1/10" cần TE xác nhận.
- **Trang Gage Info của Crossed Gage R&R** chưa đọc được; ý nghĩa Gage Tolerance (discrimination) lấy từ trang Gage Linearity and Bias và báo cáo mẫu trong WI.
- **Trang Reports của Minitab** không xác nhận việc xóa mục, template và định dạng xuất.
- **Nest as Operator:** ý nghĩa thống kê cần được TE/QE duyệt trước khi cho phép; nội dung giải thích trong app chưa qua rà soát.
- **Pattern gán operator** dựa vào thứ tự dòng, cần người dùng xác nhận.
- **Quy mô snapshot** với hàng nghìn file và hàng trăm item: chỉ chụp các item đã chọn; ngưỡng cảnh báo chưa đo.
- **Preview PDF trong Tk** không khả thi; dùng preview có cấu trúc.
- **Hai thứ tự cùng tồn tại** trong Giai đoạn 0 (thứ tự scan của panel hiện có, Worksheet Order của Dataset mới); cần giữ rõ ràng cho đến khi Giai đoạn 1 chuyển panel sang Dataset.
- **Tên trạng thái:** hằng số hiện có là `CONDITIONAL PASS` và `N/A`, trong khi yêu cầu mới dùng CAUTION và Not Evaluated. Giai đoạn 0 giữ hằng số hiện có (đổi tên sẽ làm đổi đầu ra `analyze()`, báo cáo và giao diện); quyết định đổi tên ở Giai đoạn 1.
- **Kiểm định ổn định quá trình và phân phối chuẩn** chưa cài đặt và chưa kiểm chứng với Minitab; trong thời gian đó điều kiện luôn `NOT_ASSESSED`.
- **Thay đổi bên ngoài trước Giai đoạn 0:** `ndc_from_variances` (`numeric.py`) dùng ở `statistics/grr.py` và `grr.py`, cùng test mới. Baseline lấy từ trạng thái này; chưa được so với Minitab.

## 14. Ngoài phạm vi

Attribute GRR; Gage R&R Expanded và Nested; Type 1 và Linearity/Bias; mở project Minitab; quản lý ticket/JTEFMS.

## 15. Điều kiện duyệt Giai đoạn 0

**Phạm vi được duyệt:** đúng mục 10. Cụ thể:
1. Viết và chạy baseline regression test trước khi refactor.
2. Immutable Dataset Snapshot.
3. Study / ResultSet / phát hiện stale.
4. Tách Statistics và Evaluation.
5. `analyze()` tương thích hoàn toàn.
6. Không sửa công thức thống kê hiện có.
7. Không thay đổi UI, scanner, exporter hay chức năng Data Mapping hiện tại.
8. Không tự mở rộng sang Giai đoạn 1.

**Hoàn thành** khi P0-1 đến P0-7 đều đạt.

**Báo cáo sau khi triển khai:** (1) các file được thêm hoặc sửa; (2) kết quả baseline trước và sau refactor; (3) kết quả toàn bộ regression test; (4) xác nhận không đổi công thức thống kê và Data Mapping/Excel Export; (5) các vấn đề còn tồn đọng cho Giai đoạn 1.

**Quy tắc dừng:** nếu có regression test thất bại hoặc cần đổi công thức để hoàn thành refactor, **không** tự điều chỉnh hành vi cũ; báo cáo vấn đề và nguyên nhân để người dùng quyết định.

**Thứ tự ưu tiên khi xung đột:** Correctness → Data Integrity → Backward Compatibility → Performance → UI.

## 16. Kết quả Giai đoạn 0 (30/10/2026)

**Số test.** Trước khi bắt đầu: 606 test (589 pass, 17 skip). Sau khi thêm baseline và chạy trên code **chưa refactor**: 716 (699 pass, 17 skip). Sau refactor: 790 (773 pass, 17 skip, 0 lỗi). 17 test bị skip do máy thực hiện không có thư mục `samples/` (11 test so sánh với báo cáo FT thật, 6 test ở `test_sampling.py`/`test_xlsx.py`); cần chạy trên máy có `samples/`.

| Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|
| P0-1 | Đạt | 78 case phân tích + 23 lỗi cấu hình + 6 giải thích: so sánh chuỗi JSON chính xác (kể cả thứ tự khóa, `1` khác `1.0`), xanh trước và sau refactor; fixtures không đổi (hash trước = sau). Cố ý đổi `MR_D2` hoặc một hằng số d2/d3 thì test báo lỗi, kèm đường dẫn giá trị lệch |
| P0-2 | Đạt | Test khóa RawData.xlsx và thứ tự scan xanh; 28 file Data Mapping/UI/báo cáo giữ nguyên hash |
| P0-3 | Đạt | Fingerprint trùng giữa 3 tiến trình với `PYTHONHASHSEED` khác nhau; đổi khi đổi giá trị, thứ tự, limit, định danh, nguồn dùng chung; không đổi khi đổi provenance |
| P0-4 | Đạt | Ma trận stale: dữ liệu, thứ tự, mapping, design, tùy chọn liên quan thì stale; Study Info, tiêu chí, tùy chọn không liên quan, provenance thì không (và chạy lại cho kết quả giống hệt) |
| P0-5 | Đạt | Đường chạy chỉ Evaluation không gọi `compute()` (spy); metrics giống hệt từng bit giữa các tiêu chí |
| P0-6 | Đạt, kèm lưu ý 17 test skip | 606 test cũ pass không sửa; không file test cũ nào bị đổi; ruff sạch; `--smoke-test` thoát với mã 0 |
| P0-7 | Đạt | 9 file công thức (`capability`, `grr`, `crossed`, `numeric`, `formulas`, `customers`, `normalize`, `acceptance`, `validation`) giữ nguyên hash |

**File.** Sửa 3 file có sẵn: `statistics/engine.py` (tách `compute`/`analyze`), `statistics/models.py` (thêm kiểu và hằng số), `statistics/__init__.py` (export). Thêm 3 module: `dataset.py`, `study.py`, `evaluation.py`. Thêm test: `test_regression_baseline.py`, `test_export_regression.py`, `test_dataset.py`, `test_study.py`, `baseline_support.py`, `make_baseline.py`, hai file JSON baseline.

**Hiệu năng (đo trên máy phát triển, một lần).** Tạo `Dataset` kèm fingerprint: 0.13 s cho 10 nghìn quan sát, 1.3 s cho 100 nghìn, 5.5 s cho 500 nghìn (cùng lúc `compute()` 100 nghìn quan sát capability mất 0.8 s). Ở Giai đoạn 1 cần chạy trong tác vụ nền.

**Còn tồn đọng cho Giai đoạn 1:**
1. **D2 chưa được thực thi.** Các cấu trúc (mức cảnh báo, xác nhận khác kiểm chứng, Validation Status) đã có, nhưng `evaluate()` giữ hành vi cũ để `analyze()` không đổi, nên Capability vẫn cho PASS/FAIL dù chưa xác nhận điều kiện. Chỉ đổi khi giao diện xác nhận và việc phát hiện điều kiện (đo lặp, thiếu Acquisition Order, N < 100) được làm.
2. **Hai thứ tự cùng tồn tại:** `normalize_records` (panel hiện tại) giữ thứ tự scan; `snapshot_from_records` dùng thứ tự RawData. Test khóa sự khác biệt này. Capability (moving range) bị ảnh hưởng khi chuyển panel sang Dataset.
3. `ValidationPanel` chưa dùng `Study`/`Dataset`: vẫn dùng `id(grouped)`, đổi số thập phân vẫn xóa kết quả, `expected_repeats` vẫn lấy từ Data Mapping. Báo cáo vẫn đọc `AnalysisResult`, chưa đọc `ResultSet`/`EvaluationRecord`.
4. Tên trạng thái: `CONDITIONAL PASS`/`N/A` so với CAUTION/Not Evaluated.
5. Kiểm định ổn định quá trình và phân phối chuẩn chưa cài; hai điều kiện luôn `NOT_ASSESSED`.
6. `StatisticalOptions.relevant()` giữ `assign_trials` cho cả capability vì mọi kết quả ghi lại nó trong details; đổi nó vẫn làm stale.
7. Trước Giai đoạn 0, có thay đổi từ bên ngoài ở `numeric.py` (`ndc_from_variances`), `statistics/grr.py`, `grr.py` (pre-check) và test: baseline lấy từ trạng thái đó, chưa kiểm chứng với Minitab.

## 17. Kết quả Giai đoạn 1 (30/10/2026)

**Đã làm.** Workspace **Validation & Reports** độc lập cạnh Data Mapping (hai nút dưới header; nút "Validation & Reports →" ở trang Review). Bốn tab bật dần: **Data**, **Analysis Setup**, **Results**, **Report**. `ui/validation_workspace.py` thay `ValidationPanel`; `ui/validation.py` chỉ còn các hộp thoại (mapping, file assignments, customer criteria, xác nhận điều kiện).

| Hạng mục | Cách làm |
|---|---|
| Nguồn A | Snapshot bất biến từ scan Data Mapping; Data Mapping báo thay đổi bằng bộ đếm `serial` (không còn `id(grouped)`), nên đổi lựa chọn duplicate tại chỗ cũng được nhận ra |
| Nguồn B | `statistics/importers.py` đọc RawData.xlsx của app (đưa sớm từ Giai đoạn 2: cần để dùng Validation mà không scan) |
| Study purpose / design | MSA (Variable GRR) hoặc Process Capability; GRR mặc định một appraiser, khai tên operator trên màn hình, thứ tự dòng theo operator hoặc theo lượt, **Nest as Operator** có giải thích và ghi vào Report; capability chọn within sigma, subgroup = Sample ID (có cảnh báo), chỉ số quyết định **Cpk hoặc Ppk** |
| Thứ tự dữ liệu | Worksheet (mặc định), tên file, timestamp (từ File assignments), hoặc "tôi xác nhận dòng đã theo thứ tự đo". Ba lựa chọn sau là khẳng định của người dùng và được ghi lại; chỉ timestamp và xác nhận được coi là acquisition order |
| Quick Analysis | Chọn dữ liệu rồi **Run analysis**. Bảng Results chỉ hiện cột quyết định (GRR: %SV/Tol, %Study Var, NDC, kết quả, Review; capability: Cp, Cpk, Pp, Ppk, kết quả); phần còn lại ở Calculation details và báo cáo |
| Stale | Banner + **Update results**; kết quả stale vẫn xem được nhưng không báo cáo được. Đổi customer, ngưỡng Cpk hoặc số thập phân không làm stale (số thập phân chỉ đổi cách hiển thị) |
| D2 (xác nhận điều kiện) | `Study.evaluate(gate=True)`: capability có số nhưng **không có PASS/FAIL** ("Unconfirmed") cho đến khi các Warning được xác nhận (ai, khi nào, ghi chú); báo cáo ghi "acknowledged, not verified". Điều kiện phát hiện từ dữ liệu: thiếu acquisition order (Warning), đo lặp cùng SN (Warning), N < 100 (Information), cộng hai điều kiện luôn khai báo (ổn định, phân phối chuẩn; Warning, chưa kiểm định). Xác nhận bị xóa khi chạy lại. GRR chỉ có Information |
| Báo cáo | `ReportContext`: sheet/khối Study Information, nguồn và thứ tự dữ liệu, design, tiêu chí và phiên bản, điều kiện, trạng thái kiểm chứng; "Included n of m test items" và tiêu đề "(partial report)"; chọn nội dung (chi tiết, biểu đồ, methodology, observations). Không có context thì báo cáo như cũ. Bắt buộc Gage name, Date of study, Reported by khi Generate; từ chối kết quả stale |
| `expected_repeats` | Chuyển sang Analysis Setup (điền sẵn từ Data Mapping khi có scan mới) |

**Quyết định cần lưu ý (không đổi công thức).**
1. **`assign_trials` mặc định bật** trong workspace cho GRR: RawData.xlsx không có cột Trial, nên Trial được đánh số theo thứ tự dòng trong từng sample (hoặc từng sample × operator khi khai operator). Plan line và Report nói rõ; người dùng có thể tắt. Panel cũ mặc định tắt.
2. Mọi thay đổi chỉ ở lớp thiết kế/giao diện: `Study.plan_statistics()`/`StatisticsPlan.execute()` (lấy đầu vào ngay trên luồng giao diện rồi tính trên luồng nền), `ResultSet.design`, `detect_conditions`, `report_context`. `analyze()`, công thức và file baseline **không đổi**; 17 test cần `samples/` vẫn skip.
3. Quyết định index Cpk/Ppk thêm qua `decision_metric` (`cpk`/`ppk`) nên `AnalysisConfig` không có field mới.
4. Sửa lỗi có sẵn: bộ thu rác vòng của Python có thể chạy trên luồng nền và hủy đối tượng `tkinter.font.Font` từ luồng đó; Tk chờ luồng chính khoảng 1 giây cho mỗi đối tượng, nên scan có thể treo hoặc chậm hàng chục giây (làm test giao diện chập chờn). `TaskRunner` tạm dừng GC vòng khi có tác vụ chạy.

**Chưa làm / giới hạn.** Kiểm định ổn định quá trình và phân phối chuẩn (hai điều kiện luôn `NOT_ASSESSED`); order "Custom" tự chọn ngoài tên file/timestamp; wizard xlsx/csv tổng quát và template (Giai đoạn 2-3); Save/Open Study; "Giữ và tạo kết quả mới" cạnh nút Update (chỉ có Update); phương pháp vẫn là `Pending Minitab Verification`.

## 18. Điều chỉnh định hướng (31/10/2026)

**Nguyên tắc.** Minitab là chuẩn tham chiếu chính cho Variable GRR và Normal Capability. WI của Jabil chỉ để tham khảo, không quyết định phương pháp tính, thiết kế phần mềm hay ngưỡng PASS/FAIL. Mục tiêu: phân tích và báo cáo tương tự Minitab, đơn giản hơn, dùng trực tiếp dữ liệu Data Mapping. Chưa đối chiếu được với output Minitab thì không tuyên bố tương đương ("Pending Minitab Verification").

Các mục của Giai đoạn 1 (§17) đã đổi theo nguyên tắc này; nếu có mâu thuẫn, mục này thắng:

| Mục | Trước | Sau |
|---|---|---|
| D2, xác nhận điều kiện Capability | Chưa xác nhận thì có số nhưng không có PASS/FAIL; hộp thoại xác nhận | **Bỏ.** Kết quả hiện ngay. Điều kiện thành **ghi chú và giới hạn** (thanh ghi chú, hộp "Read the notes", mục "Notes and limitations of this analysis" trong báo cáo); không chặn kết quả, không chặn báo cáo |
| Tiêu chí PASS/FAIL | Mặc định SolarEdge; Capability mặc định Cpk > 1.33 | **Tùy chọn, mặc định không có**: kết quả và báo cáo chỉ gồm thống kê. Chọn customer (GRR) hoặc "Judge against a limit" (Cpk/Ppk, Capability) mới có PASS/FAIL. Customer dựng sẵn chỉ là điểm xuất phát lấy từ WI để tham khảo |
| Cảnh báo thiết kế GRR | "WI khuyến nghị 10" | Theo Minitab: ≥ 10 part, ≥ 3 operator (trừ khi thực tế ít hơn), ≥ 2 lần đo lặp; các part nên phủ khoảng biến động thực tế của quá trình |
| Cảnh báo Capability | Theo WI | Theo Minitab: dữ liệu theo thứ tự thu thập, subgroup hợp lý, ≥ 100 điểm, quy trình ổn định, phân phối chuẩn (Box-Cox, Johnson hoặc không chuẩn nếu không); nhiều phép đo cùng SN: giải thích nguy cơ (đo hệ thống đo chứ không chỉ quá trình), không áp đặt quy trình WI |
| Within sigma | Người dùng chọn | Mặc định **tự chọn theo subgroup size** (moving range khi subgroup = 1, pooled SD khi mọi subgroup ≥ 2); vẫn chọn tay được. Các trang Minitab đã đọc không nêu estimator mặc định, nên chương trình không gọi đó là "mặc định của Minitab" |
| Trial | Đánh số theo thứ tự dòng, bật mặc định | Giữ nhưng nói rõ: chỉ để tổ chức dữ liệu GRR, không phải thứ tự đo thực tế; ghi trong ghi chú và báo cáo |
| Thứ tự dữ liệu | Worksheet mặc định | Giữ: không có run order thực tế thì giữ thứ tự worksheet, không coi SN đã sắp xếp là acquisition order, không đổi thứ tự để Cpk giống kết quả cũ |
| Preview kết quả | Bảng + biểu đồ + hộp văn bản | Thêm tab **Details** kiểu session window của Minitab: ANOVA, variance components (%Contribution), %StudyVar, %Tolerance, NDC; hoặc process data, Cp/Cpk/Pp/Ppk |
| Báo cáo | Cần đủ thông tin; có PASS/FAIL | Không cần PASS/FAIL; ghi "None: statistics only" khi không có tiêu chí; bảng tóm tắt bỏ cột Result/Review/Decision Metric |

**Chưa làm.** Kiểm định ổn định (I-MR) và chuẩn (Anderson-Darling) chỉ được nhắc trong ghi chú, chưa tính; phương pháp không chuẩn, Box-Cox, Johnson; PPM/Z/CPL/CPU riêng. Trang Minitab đã đọc không nêu rõ hiển thị Cp/Pp khi chỉ có một giới hạn; chương trình hiển thị Cpk/Ppk theo phía có sẵn và Cp/Pp là N/A, chưa đối chiếu.

## 19. Thiết kế lại Report theo mẫu Minitab (31/10/2026)

**Đối chiếu.** Hai báo cáo tham chiếu đã đọc: `GR&R for FIXTURE-FT-FX-1163-M12-#01-R01 Jabil ID P42657.pdf` (ảnh, 9 trang) và `CPK REPORT for ICT machine_MY47450178R` (PDF/PPTX, 7 trang). Bố cục lấy từ phần kết quả Minitab, không lấy trang bìa hay Summary của Jabil.

| Phần | Giữ / đổi |
|---|---|
| GRR, mỗi Test Item | **Gage R&R for [item]** (+ Gage name, Date of study, Reported by, Tolerance, Misc chỉ khi có); One-Way ANOVA Table (hoặc Two-Way With/Without Interaction kèm "α to remove interaction term"); Variance Components (VarComp, %Contribution); Gage Evaluation (StdDev, Study Var, %Study Var, %Tolerance); Number of Distinct Categories; rồi **Gage R&R (ANOVA) Report for [item]**: Components of Variation, R Chart, Measurement by Sample ID, Xbar Chart (+ by Operator và Sample ID x Operator khi crossed) |
| Capability, mỗi Test Item | **Process Capability Report for [item]**: Process Data (LSL, Target, USL, Sample Mean, Sample N, StDev(Overall), StDev(Within)), histogram với LSL/USL và đường Overall (đỏ, liền) / Within (đen, nét đứt), Overall Capability (Pp, PPL, PPU, Ppk, Cpm), Potential (Within) Capability (Cp, CPL, CPU, Cpk), Performance (PPM < LSL, > USL, Total: Observed, Expected Overall, Expected Within), "The actual process spread is represented by 6 sigma." |
| Bỏ khỏi report | PASS/FAIL, Customer, Decision Metric, ngưỡng, Validation Status, acknowledgement, fingerprint, stale, đoạn giải thích assumptions/methodology/calculation details, trang Summary, các trường Study Information ngoài Gage name / Date of study / Reported by / Misc. Chân trang chỉ ghi "DataMapperX · not an official Minitab report", ngày tạo và số trang |
| Không làm | Joint/Conditional Probability (misclassification) có trong mẫu GRR nhưng engine chưa hỗ trợ; Target và Cpm in "*" như Minitab khi không có target |
| Excel | Một sheet mỗi item (cùng bảng như PDF, giá trị đầy đủ, chỉ định dạng hiển thị) + biểu đồ gốc Excel; sheet Summary chỉ khi nhiều item; Observations là tùy chọn |

**Giá trị suy ra từ kết quả của engine (không đổi công thức).** CPL, CPU, PPL, PPU = (mean − LSL)/(3σ) và (USL − mean)/(3σ) với σ within hoặc overall; PPM quan sát = số đo ngoài giới hạn / N; PPM kỳ vọng = đuôi phân phối chuẩn với mean và σ. Đã đối chiếu CPL/CPU/PPL/PPU/Pp/Cp với số in trong báo cáo Minitab (slide C3 và I6) tới độ chính xác in ra; chưa có output Minitab của chính dữ liệu thật.

**Baseline.** Phần văn bản/biểu đồ của baseline được cập nhật có chủ đích (bỏ `calculation_rows`, `acceptance_description`, `method_description`, `gage_evaluation_rows`; cập nhật nhãn/màu biểu đồ). Đã kiểm 78 case: kết quả số, details, summary rows, review note và mọi điểm của biểu đồ không đổi.

## Nguồn Minitab đã đọc

- [Crossed Gage R&R: data considerations](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/before-you-start/data-considerations/)
- [Crossed Gage R&R: enter your data](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/perform-the-analysis/enter-your-data/)
- [Crossed Gage R&R: options](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/crossed-gage-r-r-study/perform-the-analysis/specify-the-options/)
- [Create Gage R&R Study Worksheet](https://support.minitab.com/en-us/minitab/help-and-how-to/modules/measurement-system-analysis/gage-r-and-r-study/perform-standard-study/create-gage-r-r-study-worksheet/)
- [Gage R&R Study (Expanded)](https://support.minitab.com/en-us/minitab/help-and-how-to/modules/measurement-system-analysis/gage-r-and-r-study/perform-expanded-study/gage-r-r-study-expanded/)
- [Gage Linearity and Bias: study information](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/measurement-system-analysis/how-to/gage-study/gage-linearity-and-bias-study/perform-the-analysis/specify-the-study-information/)
- [Normal Capability Analysis: data considerations](https://support.minitab.com/minitab/help-and-how-to/quality-and-process-improvement/capability-analysis/how-to/capability-analysis/normal-capability-analysis/before-you-start/data-considerations)
- [About collecting data in subgroups](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/capability-analysis/supporting-topics/data-and-data-assumptions/using-subgroups-to-assess-capability/)
- [Update results in the output pane](https://support.minitab.com/en-us/minitab/help-and-how-to/minitab-environment/interface/interface-components/update-results-in-the-output-pane/)
- [Reports in Minitab](https://support.minitab.com/en-us/minitab/help-and-how-to/minitab-environment/interface/interface-components/reports/)
