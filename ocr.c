#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <sys/stat.h>
#include <errno.h>
#include <unistd.h>
#include <dirent.h>
#include <ctype.h>
#include <tesseract/capi.h>
#include <leptonica/allheaders.h>

// Constants and Configuration
#define MAX_PATH_LENGTH 4096
#define MAX_TEXT_LENGTH 1048576  // 1MB text buffer
#define MIN_CONFIDENCE_THRESHOLD 30.0
#define DEFAULT_DPI 300
#define MAX_IMAGE_WIDTH 5000
#define MAX_IMAGE_HEIGHT 5000
#define OCR_TIMEOUT_SECONDS 120
#define LOG_BUFFER_SIZE 8192
#define MAX_LANGUAGES 10
#define VERSION_STRING "CustomOCR v2.0.1"

// Error codes
typedef enum {
    OCR_SUCCESS = 0,
    OCR_ERROR_INIT = -1,
    OCR_ERROR_FILE_NOT_FOUND = -2,
    OCR_ERROR_INVALID_IMAGE = -3,
    OCR_ERROR_MEMORY_ALLOCATION = -4,
    OCR_ERROR_PROCESSING = -5,
    OCR_ERROR_TIMEOUT = -6,
    OCR_ERROR_INVALID_PARAMETER = -7,
    OCR_ERROR_LANGUAGE_NOT_SUPPORTED = -8,
    OCR_ERROR_PERMISSION_DENIED = -9,
    OCR_ERROR_DISK_SPACE = -10
} OCRErrorCode;

// OCR Configuration Structure
typedef struct {
    char language[256];
    int page_seg_mode;
    int ocr_engine_mode;
    float min_confidence;
    int enable_preprocessing;
    int enable_deskew;
    int enable_denoising;
    int target_dpi;
    int max_width;
    int max_height;
    char whitelist_chars[1024];
    char blacklist_chars[256];
    int enable_logging;
    char log_file_path[MAX_PATH_LENGTH];
} OCRConfig;

// OCR Result Structure
typedef struct {
    char* text;
    float confidence;
    int word_count;
    int character_count;
    int processing_time_ms;
    OCRErrorCode error_code;
    char error_message[512];
    PIX* processed_image;
    int image_width;
    int image_height;
    int image_depth;
} OCRResult;

// Image Processing Parameters
typedef struct {
    float contrast_factor;
    float brightness_factor;
    float gamma_correction;
    int noise_reduction_level;
    int sharpening_level;
    int deskew_enabled;
    float rotation_angle;
    int crop_enabled;
    int crop_x, crop_y, crop_width, crop_height;
} ImageProcessingParams;

// Language Support Structure
typedef struct {
    char code[16];
    char name[64];
    char description[256];
    int is_supported;
} LanguageInfo;

// Global configuration
static OCRConfig g_ocr_config = {
    .language = "fra+eng",
    .page_seg_mode = PSM_SINGLE_UNIFORM_BLOCK,
    .ocr_engine_mode = OEM_TESSERACT_LSTM_COMBINED,
    .min_confidence = MIN_CONFIDENCE_THRESHOLD,
    .enable_preprocessing = 1,
    .enable_deskew = 1,
    .enable_denoising = 1,
    .target_dpi = DEFAULT_DPI,
    .max_width = MAX_IMAGE_WIDTH,
    .max_height = MAX_IMAGE_HEIGHT,
    .whitelist_chars = "",
    .blacklist_chars = "",
    .enable_logging = 1,
    .log_file_path = "ocr_debug.log"
};

// Supported languages array
static LanguageInfo supported_languages[] = {
    {"eng", "English", "English language pack", 1},
    {"fra", "French", "French language pack", 1},
    {"deu", "German", "German language pack", 1},
    {"spa", "Spanish", "Spanish language pack", 1},
    {"ita", "Italian", "Italian language pack", 1},
    {"por", "Portuguese", "Portuguese language pack", 1},
    {"rus", "Russian", "Russian language pack", 1},
    {"ara", "Arabic", "Arabic language pack", 1},
    {"chi_sim", "Chinese Simplified", "Simplified Chinese language pack", 1},
    {"jpn", "Japanese", "Japanese language pack", 1}
};

// Function prototypes
void log_message(const char* level, const char* format, ...);
OCRErrorCode validate_file_path(const char* file_path);
OCRErrorCode validate_image_file(const char* file_path);
char* get_file_extension(const char* file_path);
int is_supported_image_format(const char* extension);
PIX* load_image_with_validation(const char* file_path, OCRErrorCode* error);
PIX* preprocess_image_advanced(PIX* input_image, ImageProcessingParams* params);
PIX* apply_contrast_enhancement(PIX* input_image, float factor);
PIX* apply_noise_reduction(PIX* input_image, int level);
PIX* apply_sharpening(PIX* input_image, int level);
PIX* auto_deskew_image(PIX* input_image);
PIX* normalize_image_size(PIX* input_image, int target_dpi);
char* clean_ocr_text(const char* raw_text);
char* remove_noise_from_text(const char* input_text);
char* fix_common_ocr_errors(const char* input_text);
int count_words(const char* text);
float calculate_text_confidence(TessBaseAPI* handle);
OCRResult* create_ocr_result(void);
void free_ocr_result(OCRResult* result);
void print_ocr_statistics(OCRResult* result);
int benchmark_ocr_performance(const char* test_image_path);
void print_system_info(void);
void print_supported_languages(void);
OCRErrorCode test_tesseract_installation(void);
char* get_tesseract_version(void);
void cleanup_temp_files(void);
long get_file_size(const char* file_path);
int check_disk_space(const char* path, long required_bytes);
char* generate_unique_filename(const char* prefix, const char* extension);
void save_debug_image(PIX* image, const char* prefix);
OCRErrorCode batch_process_directory(const char* input_dir, const char* output_dir);
void print_usage_help(const char* program_name);
void print_version_info(void);

// Logging function with timestamp
void log_message(const char* level, const char* format, ...) {
    if (!g_ocr_config.enable_logging) return;
    
    FILE* log_file = fopen(g_ocr_config.log_file_path, "a");
    if (!log_file) return;
    
    time_t now;
    time(&now);
    struct tm* timeinfo = localtime(&now);
    
    fprintf(log_file, "[%04d-%02d-%02d %02d:%02d:%02d] [%s] ",
            timeinfo->tm_year + 1900, timeinfo->tm_mon + 1, timeinfo->tm_mday,
            timeinfo->tm_hour, timeinfo->tm_min, timeinfo->tm_sec, level);
    
    va_list args;
    va_start(args, format);
    vfprintf(log_file, format, args);
    va_end(args);
    
    fprintf(log_file, "\n");
    fclose(log_file);
}

// File validation functions
OCRErrorCode validate_file_path(const char* file_path) {
    if (!file_path || strlen(file_path) == 0) {
        log_message("ERROR", "File path is null or empty");
        return OCR_ERROR_INVALID_PARAMETER;
    }
    
    if (strlen(file_path) >= MAX_PATH_LENGTH) {
        log_message("ERROR", "File path too long: %s", file_path);
        return OCR_ERROR_INVALID_PARAMETER;
    }
    
    if (access(file_path, F_OK) != 0) {
        log_message("ERROR", "File does not exist: %s", file_path);
        return OCR_ERROR_FILE_NOT_FOUND;
    }
    
    if (access(file_path, R_OK) != 0) {
        log_message("ERROR", "No read permission for file: %s", file_path);
        return OCR_ERROR_PERMISSION_DENIED;
    }
    
    return OCR_SUCCESS;
}

OCRErrorCode validate_image_file(const char* file_path) {
    OCRErrorCode result = validate_file_path(file_path);
    if (result != OCR_SUCCESS) return result;
    
    char* extension = get_file_extension(file_path);
    if (!extension) {
        log_message("ERROR", "Could not determine file extension: %s", file_path);
        return OCR_ERROR_INVALID_IMAGE;
    }
    
    if (!is_supported_image_format(extension)) {
        log_message("ERROR", "Unsupported image format: %s", extension);
        free(extension);
        return OCR_ERROR_INVALID_IMAGE;
    }
    
    free(extension);
    
    // Check file size
    long file_size = get_file_size(file_path);
    if (file_size <= 0) {
        log_message("ERROR", "Invalid file size: %ld bytes", file_size);
        return OCR_ERROR_INVALID_IMAGE;
    }
    
    if (file_size > 100 * 1024 * 1024) { // 100MB limit
        log_message("WARNING", "Large file size: %ld bytes", file_size);
    }
    
    return OCR_SUCCESS;
}

char* get_file_extension(const char* file_path) {
    if (!file_path) return NULL;
    
    const char* dot = strrchr(file_path, '.');
    if (!dot || dot == file_path) return NULL;
    
    char* extension = malloc(strlen(dot + 1) + 1);
    if (!extension) return NULL;
    
    strcpy(extension, dot + 1);
    
    // Convert to lowercase
    for (int i = 0; extension[i]; i++) {
        extension[i] = tolower(extension[i]);
    }
    
    return extension;
}

int is_supported_image_format(const char* extension) {
    if (!extension) return 0;
    
    const char* supported_formats[] = {
        "jpg", "jpeg", "png", "bmp", "tiff", "tif", 
        "gif", "webp", "pnm", "pbm", "pgm", "ppm"
    };
    
    int num_formats = sizeof(supported_formats) / sizeof(supported_formats[0]);
    
    for (int i = 0; i < num_formats; i++) {
        if (strcmp(extension, supported_formats[i]) == 0) {
            return 1;
        }
    }
    
    return 0;
}

// Advanced image loading with validation
PIX* load_image_with_validation(const char* file_path, OCRErrorCode* error) {
    *error = validate_image_file(file_path);
    if (*error != OCR_SUCCESS) return NULL;
    
    log_message("INFO", "Loading image: %s", file_path);
    
    PIX* image = pixRead(file_path);
    if (!image) {
        log_message("ERROR", "Failed to load image with Leptonica: %s", file_path);
        *error = OCR_ERROR_INVALID_IMAGE;
        return NULL;
    }
    
    // Validate image properties
    int width = pixGetWidth(image);
    int height = pixGetHeight(image);
    int depth = pixGetDepth(image);
    
    log_message("INFO", "Image loaded: %dx%d, depth=%d", width, height, depth);
    
    if (width <= 0 || height <= 0) {
        log_message("ERROR", "Invalid image dimensions: %dx%d", width, height);
        pixDestroy(&image);
        *error = OCR_ERROR_INVALID_IMAGE;
        return NULL;
    }
    
    if (width > g_ocr_config.max_width || height > g_ocr_config.max_height) {
        log_message("WARNING", "Image exceeds maximum dimensions (%dx%d), will be resized", 
                   g_ocr_config.max_width, g_ocr_config.max_height);
    }
    
    *error = OCR_SUCCESS;
    return image;
}

// Advanced image preprocessing
PIX* preprocess_image_advanced(PIX* input_image, ImageProcessingParams* params) {
    if (!input_image || !params) return NULL;
    
    PIX* processed = pixClone(input_image);
    PIX* temp;
    
    log_message("INFO", "Starting advanced image preprocessing");
    
    // 1. Convert to grayscale if needed
    if (pixGetDepth(processed) > 8) {
        log_message("INFO", "Converting to grayscale");
        temp = pixConvertTo8(processed, 0);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 2. Apply cropping if enabled
    if (params->crop_enabled) {
        log_message("INFO", "Applying crop: %dx%d at (%d,%d)", 
                   params->crop_width, params->crop_height, params->crop_x, params->crop_y);
        
        BOX* crop_box = boxCreate(params->crop_x, params->crop_y, 
                                 params->crop_width, params->crop_height);
        if (crop_box) {
            temp = pixClipRectangle(processed, crop_box, NULL);
            if (temp) {
                pixDestroy(&processed);
                processed = temp;
            }
            boxDestroy(&crop_box);
        }
    }
    
    // 3. Apply rotation if needed
    if (fabs(params->rotation_angle) > 0.1) {
        log_message("INFO", "Applying rotation: %.2f degrees", params->rotation_angle);
        temp = pixRotate(processed, params->rotation_angle * M_PI / 180.0, 
                        L_ROTATE_AREA_MAP, L_BRING_IN_WHITE, 0, 0);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 4. Auto-deskew if enabled
    if (params->deskew_enabled) {
        log_message("INFO", "Applying auto-deskew");
        temp = auto_deskew_image(processed);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 5. Apply brightness and contrast adjustments
    if (fabs(params->brightness_factor - 1.0) > 0.01 || 
        fabs(params->contrast_factor - 1.0) > 0.01) {
        log_message("INFO", "Adjusting brightness: %.2f, contrast: %.2f", 
                   params->brightness_factor, params->contrast_factor);
        
        temp = pixGammaTRC(processed, params->gamma_correction, 0, 255);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
        
        temp = apply_contrast_enhancement(processed, params->contrast_factor);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 6. Apply noise reduction
    if (params->noise_reduction_level > 0) {
        log_message("INFO", "Applying noise reduction level: %d", params->noise_reduction_level);
        temp = apply_noise_reduction(processed, params->noise_reduction_level);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 7. Apply sharpening
    if (params->sharpening_level > 0) {
        log_message("INFO", "Applying sharpening level: %d", params->sharpening_level);
        temp = apply_sharpening(processed, params->sharpening_level);
        if (temp) {
            pixDestroy(&processed);
            processed = temp;
        }
    }
    
    // 8. Normalize image size based on DPI
    temp = normalize_image_size(processed, g_ocr_config.target_dpi);
    if (temp) {
        pixDestroy(&processed);
        processed = temp;
    }
    
    log_message("INFO", "Image preprocessing completed");
    return processed;
}

PIX* apply_contrast_enhancement(PIX* input_image, float factor) {
    if (!input_image || factor <= 0) return NULL;
    
    PIX* result = pixContrastNorm(input_image, 10, 10, (int)(130 * factor), 1, 1);
    return result ? result : pixClone(input_image);
}

PIX* apply_noise_reduction(PIX* input_image, int level) {
    if (!input_image || level <= 0) return NULL;
    
    PIX* result = input_image;
    PIX* temp;
    
    for (int i = 0; i < level && i < 3; i++) {
        // Apply median filter for noise reduction
        temp = pixMedianFilter(result, 3, 3);
        if (temp) {
            if (result != input_image) pixDestroy(&result);
            result = temp;
        }
    }
    
    return result == input_image ? pixClone(input_image) : result;
}

PIX* apply_sharpening(PIX* input_image, int level) {
    if (!input_image || level <= 0) return NULL;
    
    PIX* result = input_image;
    PIX* temp;
    
    for (int i = 0; i < level && i < 3; i++) {
        // Apply unsharp masking
        temp = pixUnsharpMasking(result, 3, 0.5);
        if (temp) {
            if (result != input_image) pixDestroy(&result);
            result = temp;
        }
    }
    
    return result == input_image ? pixClone(input_image) : result;
}

PIX* auto_deskew_image(PIX* input_image) {
    if (!input_image) return NULL;
    
    float angle, conf;
    PIX* deskewed = pixFindSkewAndDeskew(input_image, 2, &angle, &conf);
    
    if (deskewed && conf > 2.0) {
        log_message("INFO", "Auto-deskew applied: angle=%.2f, confidence=%.2f", angle, conf);
        return deskewed;
    } else {
        if (deskewed) pixDestroy(&deskewed);
        log_message("INFO", "Auto-deskew skipped: low confidence");
        return pixClone(input_image);
    }
}

PIX* normalize_image_size(PIX* input_image, int target_dpi) {
    if (!input_image || target_dpi <= 0) return NULL;
    
    int width = pixGetWidth(input_image);
    int height = pixGetHeight(input_image);
    
    // Calculate scaling factor based on target DPI
    // Assume input is 72 DPI if not specified
    float scale_factor = (float)target_dpi / 72.0;
    
    // Don't scale if the image is already large enough
    if (width >= target_dpi && height >= target_dpi) {
        scale_factor = 1.0;
    }
    
    // Limit maximum scaling to avoid memory issues
    if (scale_factor > 4.0) scale_factor = 4.0;
    if (scale_factor < 0.5) scale_factor = 0.5;
    
    if (fabs(scale_factor - 1.0) < 0.1) {
        return pixClone(input_image);
    }
    
    log_message("INFO", "Scaling image by factor: %.2f", scale_factor);
    PIX* scaled = pixScale(input_image, scale_factor, scale_factor);
    return scaled ? scaled : pixClone(input_image);
}

// Text cleaning and post-processing functions
char* clean_ocr_text(const char* raw_text) {
    if (!raw_text) return NULL;
    
    size_t len = strlen(raw_text);
    char* cleaned = malloc(len * 2 + 1); // Extra space for potential expansions
    if (!cleaned) return NULL;
    
    const char* src = raw_text;
    char* dst = cleaned;
    
    // Remove control characters and normalize whitespace
    while (*src) {
        if (*src >= 32 && *src <= 126) { // Printable ASCII
            *dst++ = *src;
        } else if (*src == '\n' || *src == '\r') {
            // Preserve line breaks but normalize them
            if (dst > cleaned && *(dst-1) != '\n') {
                *dst++ = '\n';
            }
        } else if (*src == '\t') {
            *dst++ = ' '; // Convert tabs to spaces
        } else if ((*src & 0x80) != 0) { // UTF-8 character
            *dst++ = *src; // Keep UTF-8 characters as-is
        }
        src++;
    }
    
    *dst = '\0';
    
    // Apply additional cleaning
    char* final_text = remove_noise_from_text(cleaned);
    free(cleaned);
    
    if (!final_text) return NULL;
    
    char* corrected_text = fix_common_ocr_errors(final_text);
    free(final_text);
    
    return corrected_text;
}

char* remove_noise_from_text(const char* input_text) {
    if (!input_text) return NULL;
    
    size_t len = strlen(input_text);
    char* result = malloc(len + 1);
    if (!result) return NULL;
    
    const char* src = input_text;
    char* dst = result;
    
    while (*src) {
        // Remove excessive whitespace
        if (isspace(*src)) {
            if (dst > result && !isspace(*(dst-1))) {
                *dst++ = ' ';
            }
        } else {
            *dst++ = *src;
        }
        src++;
    }
    
    *dst = '\0';
    
    // Trim leading and trailing whitespace
    char* start = result;
    while (isspace(*start)) start++;
    
    if (*start == '\0') {
        *result = '\0';
        return result;
    }
    
    char* end = result + strlen(result) - 1;
    while (end > start && isspace(*end)) end--;
    *(end + 1) = '\0';
    
    if (start != result) {
        memmove(result, start, strlen(start) + 1);
    }
    
    return result;
}

char* fix_common_ocr_errors(const char* input_text) {
    if (!input_text) return NULL;
    
    size_t len = strlen(input_text);
    char* result = malloc(len * 2 + 1);
    if (!result) return NULL;
    
    strcpy(result, input_text);
    
    // Common OCR error corrections
    struct {
        const char* wrong;
        const char* correct;
    } corrections[] = {
        {"0", "O"}, // In text context
        {"1", "l"}, // In text context
        {"5", "S"}, // In text context
        {"8", "B"}, // In text context
        {"rn", "m"},
        {"vv", "w"},
        {"VV", "W"},
        {"cl", "d"},
        {"II", "ll"},
        {".", ","}  // In numeric context
    };
    
    // Apply corrections (simplified implementation)
    // In a full implementation, context analysis would be needed
    
    return result;
}

int count_words(const char* text) {
    if (!text) return 0;
    
    int count = 0;
    int in_word = 0;
    
    while (*text) {
        if (isspace(*text)) {
            in_word = 0;
        } else if (!in_word) {
            in_word = 1;
            count++;
        }
        text++;
    }
    
    return count;
}

float calculate_text_confidence(TessBaseAPI* handle) {
    if (!handle) return 0.0;
    
    float mean_conf = TessBaseAPIMeanTextConf(handle);
    
    // Get word-level confidences for more detailed analysis
    int* word_confidences = TessBaseAPIAllWordConfidences(handle);
    if (word_confidences) {
        int word_count = 0;
        float sum_conf = 0.0;
        
        for (int i = 0; word_confidences[i] >= 0; i++) {
            sum_conf += word_confidences[i];
            word_count++;
        }
        
        if (word_count > 0) {
            float word_avg = sum_conf / word_count;
            // Weight the mean confidence more heavily
            mean_conf = (mean_conf * 0.7) + (word_avg * 0.3);
        }
        
        free(word_confidences);
    }
    
    return mean_conf;
}

// OCR Result management
OCRResult* create_ocr_result(void) {
    OCRResult* result = calloc(1, sizeof(OCRResult));
    if (!result) return NULL;
    
    result->confidence = -1.0;
    result->error_code = OCR_SUCCESS;
    strcpy(result->error_message, "");
    
    return result;
}

void free_ocr_result(OCRResult* result) {
    if (!result) return;
    
    if (result->text) {
        free(result->text);
    }
    
    if (result->processed_image) {
        pixDestroy(&result->processed_image);
    }
    
    free(result);
}

void print_ocr_statistics(OCRResult* result) {
    if (!result) return;
    
    printf("\n=== OCR Statistics ===\n");
    printf("Status: %s\n", result->error_code == OCR_SUCCESS ? "SUCCESS" : "FAILED");
    
    if (result->error_code != OCR_SUCCESS) {
        printf("Error: %s\n", result->error_message);
        return;
    }
    
    printf("Processing Time: %d ms\n", result->processing_time_ms);
    printf("Confidence Score: %.2f%%\n", result->confidence);
    printf("Character Count: %d\n", result->character_count);
    printf("Word Count: %d\n", result->word_count);
    
    if (result->processed_image) {
        printf("Image Dimensions: %dx%d (depth: %d)\n", 
               result->image_width, result->image_height, result->image_depth);
    }
    
    printf("======================\n");
}
// Enhanced OCR functions with comprehensive error handling
char* perform_ocr(const char* image_path, const char* language) {
    OCRErrorCode error;
    PIX* image = load_image_with_validation(image_path, &error);
    if (!image) return NULL;
    
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        pixDestroy(&image);
        log_message("ERROR", "Failed to create Tesseract handle");
        return NULL;
    }
    
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        log_message("ERROR", "Could not initialize tesseract with language: %s", language);
        TessBaseAPIDelete(handle);
        pixDestroy(&image);
        return NULL;
    }
    
    TessBaseAPISetImage2(handle, image);
    char* output_text = TessBaseAPIGetUTF8Text(handle);
    
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    if (output_text) {
        char* cleaned_text = clean_ocr_text(output_text);
        TessDeleteText(output_text);
        return cleaned_text;
    }
    
    return NULL;
}

char* perform_ocr_from_memory(const unsigned char* image_data, size_t data_size, const char* language) {
    if (!image_data || data_size == 0 || !language) {
        log_message("ERROR", "Invalid parameters for memory OCR");
        return NULL;
    }
    
    PIX* image = pixReadMem(image_data, data_size);
    if (!image) {
        log_message("ERROR", "Could not read image from memory");
        return NULL;
    }
    
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        pixDestroy(&image);
        log_message("ERROR", "Failed to create Tesseract handle");
        return NULL;
    }
    
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        log_message("ERROR", "Could not initialize tesseract with language: %s", language);
        TessBaseAPIDelete(handle);
        pixDestroy(&image);
        return NULL;
    }
    
    TessBaseAPISetImage2(handle, image);
    char* output_text = TessBaseAPIGetUTF8Text(handle);
    
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    if (output_text) {
        char* cleaned_text = clean_ocr_text(output_text);
        TessDeleteText(output_text);
        return cleaned_text;
    }
    
    return NULL;
}

void configure_ocr_settings(TessBaseAPI* handle) {
    if (!handle) return;
    
    // Set page segmentation mode
    TessBaseAPISetPageSegMode(handle, g_ocr_config.page_seg_mode);
    
    // Set OCR Engine Mode
    TessBaseAPISetVariable(handle, "tessedit_ocr_engine_mode", 
                          g_ocr_config.ocr_engine_mode == OEM_TESSERACT_ONLY ? "0" :
                          g_ocr_config.ocr_engine_mode == OEM_LSTM_ONLY ? "1" :
                          g_ocr_config.ocr_engine_mode == OEM_TESSERACT_LSTM_COMBINED ? "2" : "3");
    
    // Character whitelist/blacklist
    if (strlen(g_ocr_config.whitelist_chars) > 0) {
        TessBaseAPISetVariable(handle, "tessedit_char_whitelist", g_ocr_config.whitelist_chars);
    }
    
    if (strlen(g_ocr_config.blacklist_chars) > 0) {
        TessBaseAPISetVariable(handle, "tessedit_char_blacklist", g_ocr_config.blacklist_chars);
    }
    
    // Performance and accuracy settings
    TessBaseAPISetVariable(handle, "tessedit_create_hocr", "1");
    TessBaseAPISetVariable(handle, "tessedit_pageseg_mode", "6");
    TessBaseAPISetVariable(handle, "preserve_interword_spaces", "1");
    
    // Language-specific optimizations
    if (strstr(g_ocr_config.language, "fra")) {
        TessBaseAPISetVariable(handle, "tessedit_char_whitelist", 
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,€$-/:àáâãäåæçèéêëìíîïñòóôõöøùúûüýÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝ");
    }
    
    log_message("INFO", "OCR settings configured for language: %s", g_ocr_config.language);
}

char* perform_enhanced_ocr(const char* image_path, const char* language) {
    clock_t start_time = clock();
    
    OCRErrorCode error;
    PIX* image = load_image_with_validation(image_path, &error);
    if (!image) return NULL;
    
    // Set up image processing parameters
    ImageProcessingParams params = {
        .contrast_factor = 1.2,
        .brightness_factor = 1.0,
        .gamma_correction = 1.0,
        .noise_reduction_level = 1,
        .sharpening_level = 1,
        .deskew_enabled = g_ocr_config.enable_deskew,
        .rotation_angle = 0.0,
        .crop_enabled = 0
    };
    
    PIX* processed_image = NULL;
    if (g_ocr_config.enable_preprocessing) {
        processed_image = preprocess_image_advanced(image, &params);
        pixDestroy(&image);
        image = processed_image;
    }
    
    // Save debug image if logging is enabled
    if (g_ocr_config.enable_logging) {
        save_debug_image(image, "preprocessed");
    }
    
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        pixDestroy(&image);
        log_message("ERROR", "Failed to create Tesseract handle");
        return NULL;
    }
    
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        log_message("ERROR", "Could not initialize tesseract with language: %s", language);
        TessBaseAPIDelete(handle);
        pixDestroy(&image);
        return NULL;
    }
    
    configure_ocr_settings(handle);
    TessBaseAPISetImage2(handle, image);
    
    char* output_text = TessBaseAPIGetUTF8Text(handle);
    float confidence = calculate_text_confidence(handle);
    
    clock_t end_time = clock();
    double processing_time = ((double)(end_time - start_time)) / CLOCKS_PER_SEC * 1000;
    
    log_message("INFO", "OCR completed in %.2f ms with confidence %.2f%%", 
               processing_time, confidence);
    
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    if (output_text) {
        char* cleaned_text = clean_ocr_text(output_text);
        TessDeleteText(output_text);
        
        if (confidence < g_ocr_config.min_confidence) {
            log_message("WARNING", "Low confidence score: %.2f%% (threshold: %.2f%%)", 
                       confidence, g_ocr_config.min_confidence);
        }
        
        return cleaned_text;
    }
    
    log_message("ERROR", "OCR returned no text");
    return NULL;
}

float get_ocr_confidence(const char* image_path, const char* language) {
    OCRErrorCode error;
    PIX* image = load_image_with_validation(image_path, &error);
    if (!image) return -1.0;
    
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        pixDestroy(&image);
        return -1.0;
    }
    
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        TessBaseAPIDelete(handle);
        pixDestroy(&image);
        return -1.0;
    }
    
    configure_ocr_settings(handle);
    TessBaseAPISetImage2(handle, image);
    
    float confidence = calculate_text_confidence(handle);
    
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    return confidence;
}

// Comprehensive OCR processing with detailed results
OCRResult* perform_comprehensive_ocr(const char* image_path, const char* language) {
    OCRResult* result = create_ocr_result();
    if (!result) return NULL;
    
    clock_t start_time = clock();
    
    // Validate inputs
    if (!image_path || !language) {
        result->error_code = OCR_ERROR_INVALID_PARAMETER;
        strcpy(result->error_message, "Invalid input parameters");
        return result;
    }
    
    // Load and validate image
    OCRErrorCode error;
    PIX* image = load_image_with_validation(image_path, &error);
    if (!image) {
        result->error_code = error;
        snprintf(result->error_message, sizeof(result->error_message), 
                "Failed to load image: %s", image_path);
        return result;
    }
    
    // Store original image properties
    result->image_width = pixGetWidth(image);
    result->image_height = pixGetHeight(image);
    result->image_depth = pixGetDepth(image);
    
    // Preprocess image
    ImageProcessingParams params = {
        .contrast_factor = 1.2,
        .brightness_factor = 1.0,
        .gamma_correction = 1.0,
        .noise_reduction_level = 1,
        .sharpening_level = 1,
        .deskew_enabled = 1,
        .rotation_angle = 0.0,
        .crop_enabled = 0
    };
    
    PIX* processed_image = preprocess_image_advanced(image, &params);
    pixDestroy(&image);
    
    if (!processed_image) {
        result->error_code = OCR_ERROR_PROCESSING;
        strcpy(result->error_message, "Image preprocessing failed");
        return result;
    }
    
    result->processed_image = pixClone(processed_image);
    
    // Initialize Tesseract
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        result->error_code = OCR_ERROR_INIT;
        strcpy(result->error_message, "Failed to create Tesseract handle");
        pixDestroy(&processed_image);
        return result;
    }
    
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        result->error_code = OCR_ERROR_LANGUAGE_NOT_SUPPORTED;
        snprintf(result->error_message, sizeof(result->error_message), 
                "Failed to initialize with language: %s", language);
        TessBaseAPIDelete(handle);
        pixDestroy(&processed_image);
        return result;
    }
    
    // Configure and perform OCR
    configure_ocr_settings(handle);
    TessBaseAPISetImage2(handle, processed_image);
    
    char* raw_text = TessBaseAPIGetUTF8Text(handle);
    result->confidence = calculate_text_confidence(handle);
    
    pixDestroy(&processed_image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    // Process results
    if (raw_text) {
        result->text = clean_ocr_text(raw_text);
        TessDeleteText(raw_text);
        
        if (result->text) {
            result->character_count = strlen(result->text);
            result->word_count = count_words(result->text);
        }
    } else {
        result->error_code = OCR_ERROR_PROCESSING;
        strcpy(result->error_message, "OCR processing returned no text");
    }
    
    clock_t end_time = clock();
    result->processing_time_ms = ((double)(end_time - start_time)) / CLOCKS_PER_SEC * 1000;
    
    return result;
}

// Utility functions
long get_file_size(const char* file_path) {
    struct stat st;
    if (stat(file_path, &st) == 0) {
        return st.st_size;
    }
    return -1;
}

int check_disk_space(const char* path, long required_bytes) {
    // Simplified implementation - in practice, would use statvfs() on Unix
    return 1; // Assume sufficient space for now
}

char* generate_unique_filename(const char* prefix, const char* extension) {
    time_t now = time(NULL);
    char* filename = malloc(256);
    if (!filename) return NULL;
    
    snprintf(filename, 256, "%s_%ld.%s", prefix, now, extension);
    return filename;
}

void save_debug_image(PIX* image, const char* prefix) {
    if (!image || !prefix) return;
    
    char* filename = generate_unique_filename(prefix, "png");
    if (!filename) return;
    
    if (pixWrite(filename, image, IFF_PNG) == 0) {
        log_message("DEBUG", "Debug image saved: %s", filename);
    }
    
    free(filename);
}

void cleanup_temp_files(void) {
    // Clean up temporary files created during processing
    DIR* dir = opendir(".");
    if (!dir) return;
    
    struct dirent* entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strncmp(entry->d_name, "temp_", 5) == 0 || 
            strncmp(entry->d_name, "debug_", 6) == 0) {
            unlink(entry->d_name);
            log_message("DEBUG", "Cleaned up temp file: %s", entry->d_name);
        }
    }
    
    closedir(dir);
}

// System information and diagnostics
void print_system_info(void) {
    printf("\n=== System Information ===\n");
    printf("OCR Engine: %s\n", VERSION_STRING);
    printf("Tesseract Version: %s\n", get_tesseract_version());
    printf("Leptonica Version: %s\n", getLeptonicaVersion());
    
    // Test Tesseract installation
    OCRErrorCode test_result = test_tesseract_installation();
    printf("Tesseract Status: %s\n", 
           test_result == OCR_SUCCESS ? "OK" : "ERROR");
    
    printf("Configuration:\n");
    printf("  - Default Language: %s\n", g_ocr_config.language);
    printf("  - Target DPI: %d\n", g_ocr_config.target_dpi);
    printf("  - Min Confidence: %.2f%%\n", g_ocr_config.min_confidence);
    printf("  - Preprocessing: %s\n", g_ocr_config.enable_preprocessing ? "Enabled" : "Disabled");
    printf("  - Logging: %s\n", g_ocr_config.enable_logging ? "Enabled" : "Disabled");
    printf("==========================\n");
}

void print_supported_languages(void) {
    printf("\n=== Supported Languages ===\n");
    
    int num_languages = sizeof(supported_languages) / sizeof(supported_languages[0]);
    for (int i = 0; i < num_languages; i++) {
        printf("  %s: %s%s\n", 
               supported_languages[i].code,
               supported_languages[i].name,
               supported_languages[i].is_supported ? "" : " (Not Available)");
    }
    
    printf("===========================\n");
    printf("Note: Use '+' to combine languages (e.g., 'fra+eng')\n");
}

OCRErrorCode test_tesseract_installation(void) {
    TessBaseAPI* handle = TessBaseAPICreate();
    if (!handle) {
        return OCR_ERROR_INIT;
    }
    
    int result = TessBaseAPIInit3(handle, NULL, "eng");
    
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    return result == 0 ? OCR_SUCCESS : OCR_ERROR_LANGUAGE_NOT_SUPPORTED;
}

char* get_tesseract_version(void) {
    static char version[64] = {0};
    if (version[0] == '\0') {
        strncpy(version, TessVersion(), sizeof(version) - 1);
    }
    return version;
}

// Batch processing capabilities
OCRErrorCode batch_process_directory(const char* input_dir, const char* output_dir) {
    if (!input_dir || !output_dir) {
        return OCR_ERROR_INVALID_PARAMETER;
    }
    
    DIR* dir = opendir(input_dir);
    if (!dir) {
        log_message("ERROR", "Cannot open input directory: %s", input_dir);
        return OCR_ERROR_FILE_NOT_FOUND;
    }
    
    // Create output directory if it doesn't exist
    struct stat st;
    if (stat(output_dir, &st) != 0) {
        if (mkdir(output_dir, 0755) != 0) {
            log_message("ERROR", "Cannot create output directory: %s", output_dir);
            closedir(dir);
            return OCR_ERROR_PERMISSION_DENIED;
        }
    }
    
    struct dirent* entry;
    int processed_count = 0;
    int success_count = 0;
    
    log_message("INFO", "Starting batch processing: %s -> %s", input_dir, output_dir);
    
    while ((entry = readdir(dir)) != NULL) {
        if (entry->d_type != DT_REG) continue; // Skip non-regular files
        
        char* extension = get_file_extension(entry->d_name);
        if (!extension || !is_supported_image_format(extension)) {
            if (extension) free(extension);
            continue;
        }
        free(extension);
        
        // Build full paths
        char input_path[MAX_PATH_LENGTH];
        char output_path[MAX_PATH_LENGTH];
        
        snprintf(input_path, sizeof(input_path), "%s/%s", input_dir, entry->d_name);
        
        // Change extension to .txt for output
        char* base_name = strdup(entry->d_name);
        char* dot = strrchr(base_name, '.');
        if (dot) *dot = '\0';
        
        snprintf(output_path, sizeof(output_path), "%s/%s.txt", output_dir, base_name);
        free(base_name);
        
        processed_count++;
        log_message("INFO", "Processing file %d: %s", processed_count, entry->d_name);
        
        // Perform OCR
        OCRResult* result = perform_comprehensive_ocr(input_path, g_ocr_config.language);
        if (result && result->error_code == OCR_SUCCESS && result->text) {
            // Save result to file
            FILE* output_file = fopen(output_path, "w");
            if (output_file) {
                fprintf(output_file, "%s", result->text);
                fclose(output_file);
                success_count++;
                log_message("INFO", "Saved result: %s", output_path);
            } else {
                log_message("ERROR", "Cannot write to: %s", output_path);
            }
        } else {
            log_message("ERROR", "OCR failed for: %s", entry->d_name);
        }
        
        if (result) free_ocr_result(result);
    }
    
    closedir(dir);
    
    log_message("INFO", "Batch processing completed: %d/%d files successful", 
               success_count, processed_count);
    
    return processed_count > 0 ? OCR_SUCCESS : OCR_ERROR_FILE_NOT_FOUND;
}

// Performance benchmarking
int benchmark_ocr_performance(const char* test_image_path) {
    if (!test_image_path) {
        printf("Error: No test image path provided\n");
        return -1;
    }
    
    printf("\n=== OCR Performance Benchmark ===\n");
    printf("Test Image: %s\n", test_image_path);
    
    // Validate test image
    OCRErrorCode error = validate_image_file(test_image_path);
    if (error != OCR_SUCCESS) {
        printf("Error: Invalid test image\n");
        return -1;
    }
    
    // Run multiple iterations
    const int iterations = 5;
    double total_time = 0;
    float total_confidence = 0;
    int successful_runs = 0;
    
    for (int i = 0; i < iterations; i++) {
        printf("Run %d/%d... ", i + 1, iterations);
        fflush(stdout);
        
        clock_t start = clock();
        OCRResult* result = perform_comprehensive_ocr(test_image_path, g_ocr_config.language);
        clock_t end = clock();
        
        if (result && result->error_code == OCR_SUCCESS) {
            double run_time = ((double)(end - start)) / CLOCKS_PER_SEC * 1000;
            total_time += run_time;
            total_confidence += result->confidence;
            successful_runs++;
            
            printf("%.2f ms (conf: %.2f%%)\n", run_time, result->confidence);
        } else {
            printf("FAILED\n");
        }
        
        if (result) free_ocr_result(result);
    }
    
    if (successful_runs > 0) {
        printf("\nBenchmark Results:\n");
        printf("  Successful Runs: %d/%d\n", successful_runs, iterations);
        printf("  Average Time: %.2f ms\n", total_time / successful_runs);
        printf("  Average Confidence: %.2f%%\n", total_confidence / successful_runs);
        printf("  Processing Rate: %.2f images/sec\n", 
               1000.0 / (total_time / successful_runs));
    } else {
        printf("All benchmark runs failed!\n");
        return -1;
    }
    
    printf("================================\n");
    return 0;
}

// Help and usage information
void print_usage_help(const char* program_name) {
    printf("Usage: %s [OPTIONS] <command> [arguments]\n\n", program_name);
    printf("Commands:\n");
    printf("  ocr <image_path> [language]     - Perform OCR on single image\n");
    printf("  batch <input_dir> <output_dir>  - Batch process directory\n");
    printf("  benchmark <image_path>          - Run performance benchmark\n");
    printf("  test                            - Test system installation\n");
    printf("  languages                       - List supported languages\n");
    printf("  version                         - Show version information\n");
    printf("  help                            - Show this help message\n\n");
    
    printf("Options:\n");
    printf("  --language <lang>               - Set OCR language (default: fra+eng)\n");
    printf("  --confidence <threshold>        - Set minimum confidence (default: %.1f)\n", 
           MIN_CONFIDENCE_THRESHOLD);
    printf("  --dpi <value>                   - Set target DPI (default: %d)\n", DEFAULT_DPI);
    printf("  --no-preprocessing              - Disable image preprocessing\n");
    printf("  --no-deskew                     - Disable auto-deskewing\n");
    printf("  --log-file <path>               - Set log file path\n");
    printf("  --quiet                         - Disable logging\n\n");
    
    printf("Examples:\n");
    printf("  %s ocr invoice.pdf fra\n", program_name);
    printf("  %s batch ./images ./output\n", program_name);
    printf("  %s --confidence 70 ocr document.png\n", program_name);
    printf("  %s benchmark test_image.jpg\n", program_name);
}

void print_version_info(void) {
    printf("%s\n", VERSION_STRING);
    printf("Built with:\n");
    printf("  - Tesseract OCR: %s\n", get_tesseract_version());
    printf("  - Leptonica: %s\n", getLeptonicaVersion());
    printf("  - Compilation: %s %s\n", __DATE__, __TIME__);
}

// Function to perform OCR on image data in memory
char* perform_ocr_from_memory(const unsigned char* image_data, size_t data_size, const char* language) {
    TessBaseAPI* handle;
    PIX* image;
    char* output_text;
    
    // Initialize tesseract-ocr with specified language
    handle = TessBaseAPICreate();
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        fprintf(stderr, "Could not initialize tesseract.\n");
        TessBaseAPIDelete(handle);
        return NULL;
    }
    
    // Load image from memory using Leptonica
    image = pixReadMem(image_data, data_size);
    if (!image) {
        fprintf(stderr, "Could not read image from memory\n");
        TessBaseAPIEnd(handle);
        TessBaseAPIDelete(handle);
        return NULL;
    }
    
    // Set image for tesseract
    TessBaseAPISetImage2(handle, image);
    
    // Perform OCR
    output_text = TessBaseAPIGetUTF8Text(handle);
    
    // Clean up
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    return output_text;
}

// Function to set OCR configuration for better accuracy
void configure_ocr_settings(TessBaseAPI* handle) {
    // Set page segmentation mode (PSM)
    // PSM 6: Uniform block of text
    TessBaseAPISetPageSegMode(handle, PSM_SINGLE_UNIFORM_BLOCK);
    
    // Set OCR Engine Mode
    // OEM_TESSERACT_LSTM_COMBINED = 3 (Best for most cases)
    TessBaseAPISetVariable(handle, "tessedit_ocr_engine_mode", "3");
    
    // Improve accuracy for French text
    TessBaseAPISetVariable(handle, "tessedit_char_whitelist", 
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,€$-/:àáâãäåæçèéêëìíîïñòóôõöøùúûüý");
    
    // Enable confidence scores
    TessBaseAPISetVariable(handle, "tessedit_create_hocr", "1");
}

// Enhanced OCR function with preprocessing and configuration
char* perform_enhanced_ocr(const char* image_path, const char* language) {
    TessBaseAPI* handle;
    PIX* image;
    PIX* processed_image;
    char* output_text;
    
    // Initialize tesseract-ocr
    handle = TessBaseAPICreate();
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        fprintf(stderr, "Could not initialize tesseract.\n");
        TessBaseAPIDelete(handle);
        return NULL;
    }
    
    // Configure OCR settings
    configure_ocr_settings(handle);
    
    // Load and preprocess image
    image = pixRead(image_path);
    if (!image) {
        fprintf(stderr, "Could not read image: %s\n", image_path);
        TessBaseAPIEnd(handle);
        TessBaseAPIDelete(handle);
        return NULL;
    }
    
    // Image preprocessing for better OCR accuracy
    // 1. Convert to grayscale if needed
    if (pixGetDepth(image) > 8) {
        processed_image = pixConvertTo8(image, 0);
        pixDestroy(&image);
        image = processed_image;
    }
    
    // 2. Apply image enhancement
    // Increase contrast and reduce noise
    processed_image = pixContrastNorm(image, 10, 10, 130, 1, 1);
    if (processed_image) {
        pixDestroy(&image);
        image = processed_image;
    }
    
    // 3. Scale image if too small (minimum 300 DPI equivalent)
    int width = pixGetWidth(image);
    int height = pixGetHeight(image);
    if (width < 1000 || height < 1000) {
        float scale_factor = 2.0;
        processed_image = pixScale(image, scale_factor, scale_factor);
        if (processed_image) {
            pixDestroy(&image);
            image = processed_image;
        }
    }
    
    // Set processed image for tesseract
    TessBaseAPISetImage2(handle, image);
    
    // Perform OCR
    output_text = TessBaseAPIGetUTF8Text(handle);
    
    // Clean up
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    return output_text;
}

// Function to get OCR confidence score
float get_ocr_confidence(const char* image_path, const char* language) {
    TessBaseAPI* handle;
    PIX* image;
    float confidence;
    
    handle = TessBaseAPICreate();
    if (TessBaseAPIInit3(handle, NULL, language) != 0) {
        TessBaseAPIDelete(handle);
        return -1.0;
    }
    
    image = pixRead(image_path);
    if (!image) {
        TessBaseAPIEnd(handle);
        TessBaseAPIDelete(handle);
        return -1.0;
    }
    
    TessBaseAPISetImage2(handle, image);
    confidence = TessBaseAPIMeanTextConf(handle);
    
    pixDestroy(&image);
    TessBaseAPIEnd(handle);
    TessBaseAPIDelete(handle);
    
    return confidence;
}

// Command line argument parsing
int parse_arguments(int argc, char* argv[], char** command, char** param1, char** param2) {
    if (argc < 2) return 0;
    
    *command = NULL;
    *param1 = NULL;
    *param2 = NULL;
    
    int arg_index = 1;
    
    // Parse options
    while (arg_index < argc && argv[arg_index][0] == '-') {
        if (strcmp(argv[arg_index], "--language") == 0 && arg_index + 1 < argc) {
            strncpy(g_ocr_config.language, argv[arg_index + 1], sizeof(g_ocr_config.language) - 1);
            arg_index += 2;
        } else if (strcmp(argv[arg_index], "--confidence") == 0 && arg_index + 1 < argc) {
            g_ocr_config.min_confidence = atof(argv[arg_index + 1]);
            arg_index += 2;
        } else if (strcmp(argv[arg_index], "--dpi") == 0 && arg_index + 1 < argc) {
            g_ocr_config.target_dpi = atoi(argv[arg_index + 1]);
            arg_index += 2;
        } else if (strcmp(argv[arg_index], "--no-preprocessing") == 0) {
            g_ocr_config.enable_preprocessing = 0;
            arg_index++;
        } else if (strcmp(argv[arg_index], "--no-deskew") == 0) {
            g_ocr_config.enable_deskew = 0;
            arg_index++;
        } else if (strcmp(argv[arg_index], "--log-file") == 0 && arg_index + 1 < argc) {
            strncpy(g_ocr_config.log_file_path, argv[arg_index + 1], sizeof(g_ocr_config.log_file_path) - 1);
            arg_index += 2;
        } else if (strcmp(argv[arg_index], "--quiet") == 0) {
            g_ocr_config.enable_logging = 0;
            arg_index++;
        } else {
            printf("Unknown option: %s\n", argv[arg_index]);
            return 0;
        }
    }
    
    // Parse command
    if (arg_index < argc) {
        *command = argv[arg_index++];
    }
    
    // Parse parameters
    if (arg_index < argc) {
        *param1 = argv[arg_index++];
    }
    
    if (arg_index < argc) {
        *param2 = argv[arg_index++];
    }
    
    return 1;
}

// Enhanced main function with comprehensive command support
int main(int argc, char* argv[]) {
    // Initialize logging
    log_message("INFO", "OCR Engine started: %s", VERSION_STRING);
    
    char* command = NULL;
    char* param1 = NULL;
    char* param2 = NULL;
    
    if (!parse_arguments(argc, argv, &command, &param1, &param2)) {
        print_usage_help(argv[0]);
        return 1;
    }
    
    if (!command) {
        print_usage_help(argv[0]);
        return 1;
    }
    
    // Handle different commands
    if (strcmp(command, "help") == 0) {
        print_usage_help(argv[0]);
        return 0;
    }
    
    if (strcmp(command, "version") == 0) {
        print_version_info();
        return 0;
    }
    
    if (strcmp(command, "test") == 0) {
        print_system_info();
        return test_tesseract_installation() == OCR_SUCCESS ? 0 : 1;
    }
    
    if (strcmp(command, "languages") == 0) {
        print_supported_languages();
        return 0;
    }
    
    if (strcmp(command, "ocr") == 0) {
        if (!param1) {
            printf("Error: Image path required for OCR command\n");
            print_usage_help(argv[0]);
            return 1;
        }
        
        const char* language = param2 ? param2 : g_ocr_config.language;
        
        printf("Performing OCR on: %s\n", param1);
        printf("Language: %s\n", language);
        printf("Processing...\n");
        
        OCRResult* result = perform_comprehensive_ocr(param1, language);
        
        if (result) {
            if (result->error_code == OCR_SUCCESS && result->text) {
                printf("\n=== OCR Result ===\n");
                printf("%s\n", result->text);
                print_ocr_statistics(result);
            } else {
                printf("OCR failed: %s\n", result->error_message);
                free_ocr_result(result);
                return 1;
            }
            
            free_ocr_result(result);
        } else {
            printf("OCR processing failed\n");
            return 1;
        }
        
        return 0;
    }
    
    if (strcmp(command, "batch") == 0) {
        if (!param1 || !param2) {
            printf("Error: Input and output directories required for batch command\n");
            print_usage_help(argv[0]);
            return 1;
        }
        
        printf("Batch processing: %s -> %s\n", param1, param2);
        
        OCRErrorCode result = batch_process_directory(param1, param2);
        
        if (result == OCR_SUCCESS) {
            printf("Batch processing completed successfully\n");
            return 0;
        } else {
            printf("Batch processing failed\n");
            return 1;
        }
    }
    
    if (strcmp(command, "benchmark") == 0) {
        if (!param1) {
            printf("Error: Test image path required for benchmark command\n");
            print_usage_help(argv[0]);
            return 1;
        }
        
        return benchmark_ocr_performance(param1);
    }
    
    // Legacy single-argument mode for backward compatibility
    if (argc == 2 && access(argv[1], F_OK) == 0) {
        const char* image_path = argv[1];
        const char* language = g_ocr_config.language;
        
        printf("Performing OCR on: %s\n", image_path);
        printf("Language: %s\n", language);
        
        char* text = perform_enhanced_ocr(image_path, language);
        
        if (text) {
            printf("OCR Result:\n");
            printf("==========\n");
            printf("%s\n", text);
            
            float confidence = get_ocr_confidence(image_path, language);
            if (confidence >= 0) {
                printf("\nConfidence: %.2f%%\n", confidence);
            }
            
            free(text);
            return 0;
        } else {
            fprintf(stderr, "OCR failed\n");
            return 1;
        }
    }
    
    printf("Unknown command: %s\n", command);
    print_usage_help(argv[0]);
    return 1;
}

// Python C Extension Interface Functions with enhanced error handling
extern "C" {
    // Initialize OCR engine with configuration
    int ocr_init(const char* language, float min_confidence, int enable_preprocessing) {
        if (language) {
            strncpy(g_ocr_config.language, language, sizeof(g_ocr_config.language) - 1);
        }
        
        if (min_confidence > 0) {
            g_ocr_config.min_confidence = min_confidence;
        }
        
        g_ocr_config.enable_preprocessing = enable_preprocessing;
        
        log_message("INFO", "OCR engine initialized with language: %s", g_ocr_config.language);
        
        return test_tesseract_installation() == OCR_SUCCESS ? 0 : -1;
    }
    
    // Set OCR configuration
    void ocr_set_config(const char* key, const char* value) {
        if (!key || !value) return;
        
        if (strcmp(key, "language") == 0) {
            strncpy(g_ocr_config.language, value, sizeof(g_ocr_config.language) - 1);
        } else if (strcmp(key, "min_confidence") == 0) {
            g_ocr_config.min_confidence = atof(value);
        } else if (strcmp(key, "target_dpi") == 0) {
            g_ocr_config.target_dpi = atoi(value);
        } else if (strcmp(key, "enable_preprocessing") == 0) {
            g_ocr_config.enable_preprocessing = atoi(value);
        } else if (strcmp(key, "enable_deskew") == 0) {
            g_ocr_config.enable_deskew = atoi(value);
        } else if (strcmp(key, "log_file") == 0) {
            strncpy(g_ocr_config.log_file_path, value, sizeof(g_ocr_config.log_file_path) - 1);
        } else if (strcmp(key, "enable_logging") == 0) {
            g_ocr_config.enable_logging = atoi(value);
        }
        
        log_message("DEBUG", "Configuration updated: %s = %s", key, value);
    }
    
    // Get OCR configuration value
    const char* ocr_get_config(const char* key) {
        static char buffer[512];
        
        if (!key) return NULL;
        
        if (strcmp(key, "language") == 0) {
            return g_ocr_config.language;
        } else if (strcmp(key, "min_confidence") == 0) {
            snprintf(buffer, sizeof(buffer), "%.2f", g_ocr_config.min_confidence);
            return buffer;
        } else if (strcmp(key, "target_dpi") == 0) {
            snprintf(buffer, sizeof(buffer), "%d", g_ocr_config.target_dpi);
            return buffer;
        } else if (strcmp(key, "version") == 0) {
            return VERSION_STRING;
        } else if (strcmp(key, "tesseract_version") == 0) {
            return get_tesseract_version();
        }
        
        return NULL;
    }
    
    // Process file and return comprehensive result
    OCRResult* ocr_process_file_detailed(const char* file_path, const char* language) {
        if (!file_path) return NULL;
        
        const char* ocr_language = language ? language : g_ocr_config.language;
        return perform_comprehensive_ocr(file_path, ocr_language);
    }
    
    // Legacy function for simple text extraction
    char* ocr_process_file(const char* file_path, const char* language) {
        if (!file_path) return NULL;
        
        const char* ocr_language = language ? language : g_ocr_config.language;
        return perform_enhanced_ocr(file_path, ocr_language);
    }
    
    // Process image data from memory
    char* ocr_process_memory(const unsigned char* data, size_t size, const char* language) {
        if (!data || size == 0) return NULL;
        
        const char* ocr_language = language ? language : g_ocr_config.language;
        return perform_ocr_from_memory(data, size, ocr_language);
    }
    
    // Get confidence score for a file
    float ocr_get_confidence(const char* file_path, const char* language) {
        if (!file_path) return -1.0;
        
        const char* ocr_language = language ? language : g_ocr_config.language;
        return get_ocr_confidence(file_path, ocr_language);
    }
    
    // Free text memory allocated by OCR functions
    void ocr_free_text(char* text) {
        if (text) {
            free(text);
        }
    }
    
    // Free OCR result structure
    void ocr_free_result(OCRResult* result) {
        free_ocr_result(result);
    }
    
    // Batch processing function for Python
    int ocr_batch_process(const char* input_dir, const char* output_dir, const char* language) {
        if (!input_dir || !output_dir) return -1;
        
        if (language) {
            strncpy(g_ocr_config.language, language, sizeof(g_ocr_config.language) - 1);
        }
        
        OCRErrorCode result = batch_process_directory(input_dir, output_dir);
        return result == OCR_SUCCESS ? 0 : -1;
    }
    
    // Test OCR installation
    int ocr_test_installation(void) {
        return test_tesseract_installation() == OCR_SUCCESS ? 0 : -1;
    }
    
    // Get system information as JSON string
    char* ocr_get_system_info(void) {
        char* info = malloc(2048);
        if (!info) return NULL;
        
        snprintf(info, 2048,
            "{"
            "\"version\":\"%s\","
            "\"tesseract_version\":\"%s\","
            "\"leptonica_version\":\"%s\","
            "\"language\":\"%s\","
            "\"min_confidence\":%.2f,"
            "\"target_dpi\":%d,"
            "\"preprocessing_enabled\":%s,"
            "\"logging_enabled\":%s"
            "}",
            VERSION_STRING,
            get_tesseract_version(),
            getLeptonicaVersion(),
            g_ocr_config.language,
            g_ocr_config.min_confidence,
            g_ocr_config.target_dpi,
            g_ocr_config.enable_preprocessing ? "true" : "false",
            g_ocr_config.enable_logging ? "true" : "false"
        );
        
        return info;
    }
    
    // Cleanup function for Python integration
    void ocr_cleanup(void) {
        cleanup_temp_files();
        log_message("INFO", "OCR engine cleanup completed");
    }
}
