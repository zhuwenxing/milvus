#include "TimestamptzArithCompareExpr.h"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <ctime>
#include <memory>
#include <optional>
#include <variant>

#include "bitset/bitset.h"
#include "common/EasyAssert.h"
#include "common/Types.h"
#include "common/Vector.h"
#include "exec/expression/EvalCtx.h"
#include "exec/expression/Expr.h"
#include "expr/ITypeExpr.h"
#include "index/SkipIndex.h"
#include "pb/plan.pb.h"
#include "storage/PrefetchThreadPool.h"

namespace milvus {
namespace exec {

namespace {

constexpr int64_t kMicrosPerSecond = 1000000;
constexpr int64_t kMaxEpochSec = (INT64_MAX - 999999) / kMicrosPerSecond;
constexpr int64_t kMinEpochSec = (INT64_MIN + 999999) / kMicrosPerSecond;

int
SafeAddTimestampField(int base, int64_t delta) {
    const int64_t min_delta = static_cast<int64_t>(INT_MIN) - base;
    const int64_t max_delta = static_cast<int64_t>(INT_MAX) - base;
    AssertInfo(delta >= min_delta && delta <= max_delta,
               "timestamp interval arithmetic overflow: {} + {} = {}",
               base,
               delta,
               delta < 0 ? "less than INT_MIN" : "greater than INT_MAX");
    return static_cast<int>(static_cast<int64_t>(base) + delta);
}

int64_t
ApplyIntervalSign(int64_t value, int op_sign) {
    if (op_sign > 0) {
        return value;
    }
    AssertInfo(value != INT64_MIN,
               "timestamp interval arithmetic overflow: cannot negate {}",
               value);
    return -value;
}

constexpr int64_t
FloorDiv(int64_t a, int64_t b) {
    const int64_t q = a / b;
    return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q;
}

// Howard Hinnant's civil-from-days / days-from-civil algorithms. Pure integer
// arithmetic, identical to the proleptic-Gregorian math libc gmtime_r/timegm
// perform under UTC; widened to int64 inputs so tm-style out-of-range day
// values keep their linear carry into adjacent months.
constexpr int64_t
DaysFromCivil(int64_t y, int64_t m, int64_t d) {
    y -= m <= 2;
    const int64_t era = (y >= 0 ? y : y - 399) / 400;
    const int64_t yoe = y - era * 400;  // [0, 399]
    const int64_t doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1;
    const int64_t doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}

struct CivilDate {
    int64_t year;
    int64_t month;  // [1, 12]
    int64_t day;    // [1, 31]
};

constexpr CivilDate
CivilFromDays(int64_t z) {
    z += 719468;
    const int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    const int64_t doe = z - era * 146097;  // [0, 146096]
    const int64_t yoe =
        (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;  // [0, 399]
    const int64_t y = yoe + era * 400;
    const int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);  // [0, 365]
    const int64_t mp = (5 * doy + 2) / 153;                       // [0, 11]
    const int64_t d = doy - (153 * mp + 2) / 5 + 1;               // [1, 31]
    const int64_t m = mp < 10 ? mp + 3 : mp - 9;                  // [1, 12]
    return {y + (m <= 2), m, d};
}

// Interval components with the arithmetic sign already applied; hoisted out
// of the per-row loop.
struct SignedInterval {
    int64_t years;
    int64_t months;
    int64_t days;
    int64_t hours;
    int64_t minutes;
    int64_t seconds;
};

// op_sign == 0 means "no arithmetic" (ArithOpType::Unknown), otherwise ±1.
struct PreparedArith {
    int op_sign;
    SignedInterval interval;
};

PreparedArith
PrepareArith(proto::plan::ArithOpType arith_op,
             const proto::plan::Interval& interval) {
    switch (arith_op) {
        case proto::plan::ArithOpType::Add:
            return {1,
                    {ApplyIntervalSign(interval.years(), 1),
                     ApplyIntervalSign(interval.months(), 1),
                     ApplyIntervalSign(interval.days(), 1),
                     ApplyIntervalSign(interval.hours(), 1),
                     ApplyIntervalSign(interval.minutes(), 1),
                     ApplyIntervalSign(interval.seconds(), 1)}};
        case proto::plan::ArithOpType::Sub:
            return {-1,
                    {ApplyIntervalSign(interval.years(), -1),
                     ApplyIntervalSign(interval.months(), -1),
                     ApplyIntervalSign(interval.days(), -1),
                     ApplyIntervalSign(interval.hours(), -1),
                     ApplyIntervalSign(interval.minutes(), -1),
                     ApplyIntervalSign(interval.seconds(), -1)}};
        case proto::plan::ArithOpType::Unknown:
            return {0, {}};
        default:
            ThrowInfo(UnexpectedError,
                      "unsupported arithmetic op for "
                      "timestamptz_arith_compare_expr: {}",
                      arith_op);
    }
}

int64_t
ApplySignedInterval(int64_t current_ts_us, const PreparedArith& arith) {
    if (arith.op_sign == 0) {
        return current_ts_us;
    }

    // Floor division to correctly handle pre-epoch (negative) timestamps.
    // Keep the remainder separate so INT64_MIN does not overflow while
    // reconstructing the sub-second component.
    int64_t epoch_sec = current_ts_us / kMicrosPerSecond;
    int64_t sub_sec_us = current_ts_us % kMicrosPerSecond;
    if (sub_sec_us < 0) {
        --epoch_sec;
        sub_sec_us += kMicrosPerSecond;
    }

    // Explode epoch seconds into civil fields (identical to gmtime_r).
    const int64_t days = FloorDiv(epoch_sec, 86400);
    const int64_t secs_of_day = epoch_sec - days * 86400;  // [0, 86399]
    const CivilDate civil = CivilFromDays(days);
    const int64_t tm_year = civil.year - 1900;
    AssertInfo(tm_year >= INT_MIN && tm_year <= INT_MAX,
               "gmtime_r failed for timestamp {} us",
               current_ts_us);

    const int new_year =
        SafeAddTimestampField(static_cast<int>(tm_year), arith.interval.years);
    const int new_mon = SafeAddTimestampField(static_cast<int>(civil.month - 1),
                                              arith.interval.months);
    const int new_mday =
        SafeAddTimestampField(static_cast<int>(civil.day), arith.interval.days);
    const int new_hour = SafeAddTimestampField(
        static_cast<int>(secs_of_day / 3600), arith.interval.hours);
    const int new_min = SafeAddTimestampField(
        static_cast<int>(secs_of_day % 3600 / 60), arith.interval.minutes);
    const int new_sec = SafeAddTimestampField(
        static_cast<int>(secs_of_day % 60), arith.interval.seconds);

    // Recombine (identical to timegm): normalize the month overflow into the
    // year, then every finer field is a fixed-length offset under UTC.
    const int64_t total_months = static_cast<int64_t>(new_year) * 12 + new_mon;
    const int64_t norm_year = FloorDiv(total_months, 12);
    const int64_t norm_mon = total_months - norm_year * 12;  // [0, 11]
    int64_t new_epoch_sec;
    if (norm_year < -1500000000LL || norm_year > 1500000000LL) {
        // Beyond ~1.5 billion years libc mktime's internal arithmetic can
        // overflow in implementation-defined ways (it may even "fail" and
        // return -1). Defer to the real call so even that domain keeps
        // bit-identical behavior.
        struct std::tm tm_buf = {};
        tm_buf.tm_year = new_year;
        tm_buf.tm_mon = new_mon;
        tm_buf.tm_mday = new_mday;
        tm_buf.tm_hour = new_hour;
        tm_buf.tm_min = new_min;
        tm_buf.tm_sec = new_sec;
        new_epoch_sec = static_cast<int64_t>(::timegm(&tm_buf));
    } else {
        new_epoch_sec =
            DaysFromCivil(norm_year + 1900, norm_mon + 1, 1) * 86400 +
            static_cast<int64_t>(new_mday - 1) * 86400 +
            static_cast<int64_t>(new_hour) * 3600 +
            static_cast<int64_t>(new_min) * 60 + new_sec;
    }

    AssertInfo(new_epoch_sec >= kMinEpochSec && new_epoch_sec <= kMaxEpochSec,
               "timestamp after interval arithmetic out of representable "
               "range: {} seconds from epoch",
               new_epoch_sec);
    return new_epoch_sec * kMicrosPerSecond + sub_sec_us;
}

int64_t
ApplyTimestampInterval(int64_t current_ts_us,
                       proto::plan::ArithOpType arith_op,
                       const proto::plan::Interval& interval) {
    return ApplySignedInterval(current_ts_us, PrepareArith(arith_op, interval));
}

bool
CompareTimestamp(int64_t lhs, int64_t rhs, proto::plan::OpType compare_op) {
    switch (compare_op) {
        case proto::plan::OpType::Equal:
            return lhs == rhs;
        case proto::plan::OpType::NotEqual:
            return lhs != rhs;
        case proto::plan::OpType::GreaterThan:
            return lhs > rhs;
        case proto::plan::OpType::GreaterEqual:
            return lhs >= rhs;
        case proto::plan::OpType::LessThan:
            return lhs < rhs;
        case proto::plan::OpType::LessEqual:
            return lhs <= rhs;
        default:
            ThrowInfo(UnexpectedError,
                      "unsupported compare op for "
                      "timestamptz_arith_compare_expr: {}",
                      compare_op);
    }
}

bool
EvaluateTimestamp(int64_t current_ts_us,
                  proto::plan::ArithOpType arith_op,
                  const proto::plan::Interval& interval,
                  proto::plan::OpType compare_op,
                  int64_t compare_us) {
    const auto final_us =
        ApplyTimestampInterval(current_ts_us, arith_op, interval);
    return CompareTimestamp(final_us, compare_us, compare_op);
}

milvus::bitset::CompareOpType
ToBitsetCompareOp(proto::plan::OpType compare_op) {
    switch (compare_op) {
        case proto::plan::OpType::Equal:
            return milvus::bitset::CompareOpType::EQ;
        case proto::plan::OpType::NotEqual:
            return milvus::bitset::CompareOpType::NE;
        case proto::plan::OpType::GreaterThan:
            return milvus::bitset::CompareOpType::GT;
        case proto::plan::OpType::GreaterEqual:
            return milvus::bitset::CompareOpType::GE;
        case proto::plan::OpType::LessThan:
            return milvus::bitset::CompareOpType::LT;
        case proto::plan::OpType::LessEqual:
            return milvus::bitset::CompareOpType::LE;
        default:
            ThrowInfo(UnexpectedError,
                      "unsupported compare op for "
                      "timestamptz_arith_compare_expr: {}",
                      compare_op);
    }
}

// Loop-invariant form of `ts <arith_op> fixed_interval <compare_op>
// compare_us`: when the interval has no year/month component (or no
// arithmetic at all), every adjusted field is a fixed number of seconds, so
// the predicate reduces to `ts <compare_op> compare_us - delta_us`.
//
// row_lo/row_hi bound the input values for which `ts + delta_us` stays inside
// the representable range that the calendar path asserts on; rows outside
// must still take the calendar path so its AssertInfo fires identically.
struct FastCompare {
    int64_t bound;
    int64_t row_lo;
    int64_t row_hi;
};

std::optional<FastCompare>
TryFastCompare(proto::plan::ArithOpType arith_op,
               proto::plan::OpType compare_op,
               const proto::plan::Interval& interval,
               int64_t compare_us) {
    switch (compare_op) {
        case proto::plan::OpType::Equal:
        case proto::plan::OpType::NotEqual:
        case proto::plan::OpType::GreaterThan:
        case proto::plan::OpType::GreaterEqual:
        case proto::plan::OpType::LessThan:
        case proto::plan::OpType::LessEqual:
            break;
        default:
            // The SIMD compare and the skip index only know the six scalar
            // comparisons; anything else keeps the per-row throw behavior.
            return std::nullopt;
    }
    if (arith_op == proto::plan::ArithOpType::Unknown) {
        return FastCompare{compare_us, INT64_MIN, INT64_MAX};
    }
    if (arith_op != proto::plan::ArithOpType::Add &&
        arith_op != proto::plan::ArithOpType::Sub) {
        return std::nullopt;
    }
    if (interval.years() != 0 || interval.months() != 0) {
        return std::nullopt;
    }
    const int op_sign = arith_op == proto::plan::ArithOpType::Add ? 1 : -1;
    const int64_t components[4] = {interval.days(),
                                   interval.hours(),
                                   interval.minutes(),
                                   interval.seconds()};
    const int64_t weights[4] = {86400, 3600, 60, 1};
    // Every component must fit the SafeAddTimestampField bounds of the
    // calendar path for every row (the largest tm field base is 60), so that
    // no evaluated row can throw the interval-overflow AssertInfo.
    constexpr int64_t kMaxComponent = INT32_MAX - 64;
    __int128 delta_sec = 0;
    for (int k = 0; k < 4; ++k) {
        int64_t v = components[k];
        if (op_sign < 0) {
            if (v == INT64_MIN) {
                return std::nullopt;  // ApplyIntervalSign would throw
            }
            v = -v;
        }
        if (v < -kMaxComponent || v > kMaxComponent) {
            return std::nullopt;
        }
        delta_sec += static_cast<__int128>(v) * weights[k];
    }
    const __int128 delta_us = delta_sec * kMicrosPerSecond;
    const __int128 bound = static_cast<__int128>(compare_us) - delta_us;
    if (bound > INT64_MAX || bound < INT64_MIN) {
        return std::nullopt;
    }
    // Representable range of `ts + delta`: the calendar path asserts
    // floor(ts/1e6) + delta_sec stays within [kMinEpochSec, kMaxEpochSec].
    const __int128 row_lo =
        (static_cast<__int128>(kMinEpochSec) - delta_sec) * kMicrosPerSecond;
    const __int128 row_hi =
        (static_cast<__int128>(kMaxEpochSec) - delta_sec) * kMicrosPerSecond +
        999999;
    return FastCompare{
        static_cast<int64_t>(bound),
        row_lo < INT64_MIN ? INT64_MIN : static_cast<int64_t>(row_lo),
        row_hi > INT64_MAX ? INT64_MAX : static_cast<int64_t>(row_hi)};
}

}  // namespace

std::string
PhyTimestamptzArithCompareExpr::ToString() const {
    return expr_->ToString();
}

void
PhyTimestamptzArithCompareExpr::DetermineExecPath() {
    // Prefer field data when it is present. TIMESTAMPTZ calendar arithmetic
    // cannot be transformed into a scalar-index range query, and keeping the
    // raw-data path also preserves its batch cursor when another raw predicate
    // is evaluated alongside it.
    if (num_data_chunk_ > 0 || active_count_ == 0) {
        exec_path_ = ExprExecPath::RawData;
        return;
    }

    // An index-only sealed segment can still evaluate the expression if its
    // scalar index retains the original values for Reverse_Lookup().
    SegmentExpr::DetermineExecPath();
    if (exec_path_ == ExprExecPath::ScalarIndex && num_index_chunk_ == 1) {
        using Index = index::ScalarIndex<int64_t>;
        auto index_ptr = dynamic_cast<const Index*>(pinned_index_[0].get());
        if (index_ptr != nullptr && index_ptr->HasRawData()) {
            return;
        }
    }

    ThrowInfo(UnexpectedError,
              "TIMESTAMPTZ arithmetic comparison requires field data or a "
              "scalar index with raw data for field {}",
              field_id_.get());
}

void
PhyTimestamptzArithCompareExpr::Eval(EvalCtx& context, VectorPtr& result) {
    WaitPrefetch();
    auto input = context.get_offset_input();
    SetHasOffsetInput((input != nullptr));
    result = ExecCompareVisitorImpl<int64_t>(input);
}

template <typename T>
VectorPtr
PhyTimestamptzArithCompareExpr::ExecCompareVisitorImpl(OffsetVector* input) {
    if (exec_path_ == ExprExecPath::ScalarIndex) {
        return ExecCompareVisitorImplForIndex<T>(input);
    }
    return ExecCompareVisitorImplForAll<T>(input);
}

template <typename T>
VectorPtr
PhyTimestamptzArithCompareExpr::ExecCompareVisitorImplForIndex(
    OffsetVector* input) {
    using Index = index::ScalarIndex<T>;
    if (!arg_inited_) {
        interval_ = expr_->interval_;
        compare_value_.SetValue<T>(expr_->compare_value_);
        arg_inited_ = true;
    }

    const auto arith_op = expr_->arith_op_;
    const auto compare_op = expr_->compare_op_;
    const auto compare_value = compare_value_.GetValue<T>();
    const auto interval = interval_;
    const auto fast =
        TryFastCompare(arith_op, compare_op, interval, compare_value);
    const int64_t real_batch_size =
        input != nullptr ? input->size() : GetNextBatchSize();
    if (real_batch_size == 0) {
        return nullptr;
    }
    const int64_t eval_size =
        input != nullptr ? real_batch_size : active_count_;

    auto exec_index = [arith_op,
                       compare_op,
                       fast]<FilterType filter_type = FilterType::sequential>(
                          Index* index_ptr,
                          int64_t size,
                          T compare_value,
                          const proto::plan::Interval& interval,
                          const int32_t* offsets = nullptr) {
        TargetBitmap result(size, false);
        const int64_t compare_us = compare_value;
        for (int64_t i = 0; i < size; ++i) {
            size_t offset = i;
            if constexpr (filter_type == FilterType::random) {
                offset = offsets == nullptr ? i : offsets[i];
            }
            auto raw = index_ptr->Reverse_Lookup(offset);
            if (raw.has_value()) {
                const int64_t v = raw.value();
                if (fast && v >= fast->row_lo && v <= fast->row_hi) {
                    result[i] = CompareTimestamp(v, fast->bound, compare_op);
                } else {
                    // Out-of-range rows still take the calendar path so its
                    // representable-range AssertInfo fires identically.
                    result[i] = EvaluateTimestamp(
                        v, arith_op, interval, compare_op, compare_us);
                }
            }
        }
        return result;
    };

    VectorPtr result;
    if (input != nullptr) {
        result = ProcessIndexChunksByOffsets<T>(
            exec_index, input, eval_size, compare_value, interval);
    } else {
        result = ProcessIndexChunks<T>(
            exec_index, eval_size, compare_value, interval);
    }
    AssertInfo(result != nullptr && result->size() == real_batch_size,
               "internal error: expr processed rows {} not equal "
               "expect batch size {}",
               result == nullptr ? 0 : result->size(),
               real_batch_size);
    return result;
}

template <typename T>
VectorPtr
PhyTimestamptzArithCompareExpr::ExecCompareVisitorImplForAll(
    OffsetVector* input) {
    if (!arg_inited_) {
        interval_ = expr_->interval_;
        compare_value_.SetValue<T>(expr_->compare_value_);
        arg_inited_ = true;
    }

    auto arith_op = expr_->arith_op_;
    auto compare_op = expr_->compare_op_;
    auto compare_value = this->compare_value_.GetValue<T>();
    auto interval = interval_;
    const auto fast =
        TryFastCompare(arith_op, compare_op, interval, compare_value);

    auto real_batch_size =
        has_offset_input_ ? input->size() : GetNextBatchSize();
    if (real_batch_size == 0) {
        return nullptr;
    }

    auto res_vec =
        std::make_shared<ColumnVector>(TargetBitmap(real_batch_size, false),
                                       TargetBitmap(real_batch_size, true));

    TargetBitmapView res(res_vec->GetRawData(), real_batch_size);
    TargetBitmapView valid_res(res_vec->GetValidRawData(), real_batch_size);

    // Set by the skip-index callback before each chunk is evaluated: whether
    // the chunk's min/max stats leave any row whose ts + delta could exceed
    // the representable range. Conservative "true" when no stats exist.
    bool chunk_may_overflow = true;
    std::function<bool(const milvus::SkipIndex&, FieldId, int)> skip_func;
    if (fast) {
        skip_func = [op_ctx = op_ctx_,
                     compare_op,
                     bound = fast->bound,
                     row_lo = fast->row_lo,
                     row_hi = fast->row_hi,
                     &chunk_may_overflow](const milvus::SkipIndex& skip_index,
                                          FieldId field_id,
                                          int64_t chunk_id) {
            if (skip_index.CanSkipUnaryRange<T>(op_ctx,
                                                field_id,
                                                chunk_id,
                                                compare_op,
                                                static_cast<T>(bound))) {
                return true;
            }
            chunk_may_overflow =
                !skip_index.CanSkipUnaryRange<T>(
                    op_ctx,
                    field_id,
                    chunk_id,
                    proto::plan::OpType::GreaterThan,
                    static_cast<T>(row_hi)) ||
                !skip_index.CanSkipUnaryRange<T>(op_ctx,
                                                 field_id,
                                                 chunk_id,
                                                 proto::plan::OpType::LessThan,
                                                 static_cast<T>(row_lo));
            return false;
        };
    }

    auto exec_sub_batch =
        [arith_op,
         compare_op,
         fast,
         &chunk_may_overflow]<FilterType filter_type = FilterType::sequential>(
            const T* data,
            ValidityView valid_data,
            const int32_t* offsets,
            const int size,
            TargetBitmapView res,
            TargetBitmapView valid_res,
            T compare_value,
            proto::plan::Interval interval) {
            if (data == nullptr) {
                return;
            }
            const int64_t compare_us = compare_value;
            if (fast) {
                res.inplace_compare_val<T>(
                    data, size, fast->bound, ToBitsetCompareOp(compare_op));
                if (chunk_may_overflow) {
                    for (int i = 0; i < size; ++i) {
                        if (valid_data && !valid_data[i]) {
                            // NULL never matches, under either polarity
                            // (three-valued logic).
                            res[i] = valid_res[i] = false;
                            continue;
                        }
                        if (data[i] < fast->row_lo || data[i] > fast->row_hi)
                            [[unlikely]] {
                            // Reproduces the calendar path's representable-range
                            // AssertInfo for ts + delta out of range.
                            res[i] = EvaluateTimestamp(data[i],
                                                       arith_op,
                                                       interval,
                                                       compare_op,
                                                       compare_us);
                        }
                    }
                } else {
                    ApplyValidMask(valid_data, res, valid_res, size);
                }
                return;
            }
            // Calendar path: the signed interval is loop-invariant; materialize
            // it lazily on the first evaluated row so unsupported-op and
            // INT64_MIN-interval errors fire exactly where they did before.
            std::optional<PreparedArith> prepared;
            for (int i = 0; i < size; ++i) {
                if (valid_data && !valid_data[i]) {
                    // NULL never matches, under either polarity (three-valued
                    // logic); do not evaluate the storage placeholder value.
                    res[i] = valid_res[i] = false;
                    continue;
                }
                if (!prepared) {
                    prepared.emplace(PrepareArith(arith_op, interval));
                }
                res[i] =
                    CompareTimestamp(ApplySignedInterval(data[i], *prepared),
                                     compare_us,
                                     compare_op);
            }
        };
    int64_t processed_size;
    if (has_offset_input_) {
        processed_size = ProcessDataByOffsets<T>(exec_sub_batch,
                                                 skip_func,
                                                 input,
                                                 res,
                                                 valid_res,
                                                 compare_value,
                                                 interval);
    } else {
        processed_size = ProcessDataChunks<T>(
            exec_sub_batch, skip_func, res, valid_res, compare_value, interval);
    }
    AssertInfo(processed_size == real_batch_size,
               "internal error: expr processed rows {} not equal "
               "expect batch size {}",
               processed_size,
               real_batch_size);

    return res_vec;
}

}  // namespace exec
}  // namespace milvus
