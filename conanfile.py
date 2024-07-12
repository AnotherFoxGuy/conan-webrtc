import os
from conan import ConanFile
from conan.tools.files import replace_in_file, chdir, copy
from conan.tools.layout import basic_layout


class WebrtcConan(ConanFile):
    name = "google-webrtc"
    # versions https://chromiumdash.appspot.com/releases?platform=Linux
    # the version 83.0.4103.61 means v83, branch head 4103 (daily branches)
    # https://groups.google.com/forum/#!msg/discuss-webrtc/Ozvbd0p7Q1Y/M4WN2cRKCwAJ
    version = "124"
    _branchHead = "6367"
    license = "MIT"
    author = "Markus Lanner <contact@markus-lanner.com>"
    url = "github.com/freckled-dev/conan-google-webrtc"
    description = "Google Webrtc"
    topics = ("webrtc", "google")
    settings = "os", "compiler", "build_type", "arch"
    options = {"shared": [False], "use_h264": [True, False]}
    source_buildenv = True
    default_options = {"shared": False, "use_h264": True}
    default_user = "overte"
    default_channel = "stable"

    def layout(self):
        basic_layout(self, "src")

    def build_requirements(self):
        self.tool_requires("depot_tools/20240712@overte/stable")

    def configure(self):
        compiler = self.settings.compiler
        if compiler == "gcc" or compiler == "clang":
            # due to webrtc using its own clang. no gcc version is needed. results in better cache hit-rate
            # del self.settings.compiler.version
            del self.settings.compiler

    def source(self):
        self.run("gclient")
        self.run("fetch --nohooks webrtc")
        with chdir(self, "src"):
            self.run(
                "git checkout -b %s branch-heads/%s" % (self.version, self._branchHead)
            )
            self.run("gclient sync -D")

    def _src_dir(self):
        return os.path.join(self.source_folder, "src")

    def _is_debug(self):
        build_type = self.settings.get_safe("build_type", default="Release")
        return build_type == "Debug"

    def _is_release_with_debug_information(self):
        build_type = self.settings.get_safe("build_type", default="Release")
        return build_type == "RelWithDebInfo"

    def build(self):
        self._patch_runtime()
        args = []
        # no bundled libc++
        # if self.settings.os != "iOS":
        # args.append("use_custom_libcxx=false use_custom_libcxx_for_host=false ")
        # args.append("use_custom_libcxx_for_host=false ")
        # needed on linux 64bit, else there will be compile errors,
        # like `std::__1::__next_prime`
        args.append("use_custom_libcxx=false")
        if self.settings.arch == "armv8" or self.settings.arch == "armv7":
            # set host cxx, else you might get the error `version `GLIBCXX_3.4.26' not found` when running `protoc`
            args.append("use_custom_libcxx_for_host=true")
        args.append("treat_warnings_as_errors=false")
        # does not work well! check https://groups.google.com/g/discuss-webrtc/c/muT4irg2dvI/m/X84U9K7STi8J for patch
        # args.append("rtc_build_ssl=false "
        # args.append('rtc_ssl_root=\\"/usr\\" '
        if self._is_debug():
            args.append("is_debug=true")
        else:
            args.append("is_debug=false")
        # no tests, else the windows debug version will not compile
        args.append("rtc_include_tests=false libyuv_include_tests=false")
        # no tools
        args.append("rtc_build_tools=false")
        if self.options.use_h264:
            args.append(
                'rtc_use_h264=true proprietary_codecs=true ffmpeg_branding=\\"Chrome\\"'
            )
        if self.settings.os == "Windows":
            args + self._create_windows_arguments()
        if self.settings.os == "Linux":
            args + self._create_linux_arguments()
        if self.settings.os == "Macos":
            args + self._create_macos_arguments()
        if self.settings.os == "iOS":
            args + self._create_ios_arguments()
        call = 'gn gen "%s" --args="%s"' % (self.build_folder, " ".join(args))
        self.output.info("call: %s" % (call))

        with chdir(self, self._src_dir()):
            self.run(call)
            # show configuration
            # self.run('gn args --list "%s"' % (self.build_folder))
        with chdir(self, self.build_folder):
            self.run("ninja")

    def _patch_runtime(self):
        # https://groups.google.com/forum/#!topic/discuss-webrtc/f44XZnQDNIA
        # https://stackoverflow.com/questions/49083754/linking-webrtc-with-qt-on-windows
        # https://docs.conan.io/en/latest/reference/tools.html#tools-replace-in-file
        # TODO check the actually set runtime
        if self.settings.os == "Windows":
            with chdir(self, self._src_dir()):
                build_gn_file = os.path.join("build", "config", "win", "BUILD.gn")
                replace_in_file(
                    self,
                    build_gn_file,
                    'configs = [ ":static_crt" ]',
                    'configs = [ ":dynamic_crt" ]',
                )

                thread_file = os.path.join("rtc_base", "thread.cc")
                # https://stackoverflow.com/questions/62218555/webrtc-stddeque-iterator-exception-when-rtc-dcheck-is-on
                # there's a bug with iterator debug
                replace_in_file(
                    self,
                    thread_file,
                    "#if RTC_DCHECK_IS_ON",
                    "#if 0 // patched in conanfile, RTC_DCHECK_IS_ON",
                )
        if self.settings.os == "Linux":
            with chdir(self, self._src_dir()):
                clockdrift_detector_file = os.path.join(
                    "modules", "audio_processing", "aec3", "clockdrift_detector.h"
                )
                # missing `std::` wont compile with gcc10
                replace_in_file(
                    self,
                    clockdrift_detector_file,
                    " size_t stability_counter_;",
                    " std::size_t stability_counter_;",
                )
        if self.settings.os == "Macos":
            pass

        # there is a `include <cstring>` missing when not compiling with
        # their stdcxx (`use_custom_libcxx`)
        with chdir(self, self._src_dir()):
            stack_copier_signal_file = os.path.join(
                "base", "profiler", "stack_copier_signal.cc"
            )
            replace_in_file(
                self,
                stack_copier_signal_file,
                "#include <syscall.h>",
                """#include <syscall.h>
                   #include <cstring>""",
            )

    def _create_windows_arguments(self):
        # remove visual_studio_version? according to documentation this value is always 2015
        args = ["is_clang=false visual_studio_version=2019"]
        # args = ""
        if self._is_debug():
            # if not set the compilation will fail with:
            # _iterator_debug_level value '0' doesn't match value '2'
            # does not compile if tests and tools gets compiled in!
            args.append("enable_iterator_debugging=true")
            # pass
        return args

    def _create_linux_arguments(self):
        with chdir(self, self._src_dir()):
            self.run("./build/linux/sysroot_scripts/install-sysroot.py --arch=amd64")
            if self.settings.arch == "armv8":
                self.run(
                    "./build/linux/sysroot_scripts/install-sysroot.py --arch=arm64"
                )
            if self.settings.arch == "armv7":
                self.run("./build/linux/sysroot_scripts/install-sysroot.py --arch=arm")
        args = ["use_rtti=true"]
        if self.settings.arch != "armv8" and self.settings.arch != "armv7":
            args.append("use_sysroot=false")
        # compiler = self.settings.compiler
        # if compiler == "gcc":
        #     args.append("is_clang=false use_gold=false use_lld=false")
        # else:
        #     self.output.error("the compiler '%s' is not tested" % (compiler))
        # if tools.which('ccache'):
        #     args.append('cc_wrapper=\\"ccache\\"')
        if self.settings.arch == "armv8":
            args.append('target_cpu=\\"arm64\\"')
        if self.settings.arch == "armv7":
            args.append('target_cpu=\\"arm\\"')
        if self._is_release_with_debug_information():
            # '2' results in a ~450mb static library
            # args.append('symbol_level=2 ')
            args.append("symbol_level=1")
        return args

    def _create_macos_arguments(self):
        args = ["use_rtti=true", "use_sysroot=false"]
        # if tools.which('ccache'):
        #     args.append('cc_wrapper=\\"ccache\\" '
        if self._is_release_with_debug_information():
            # '2' results in a ~450mb static library
            # args.append('symbol_level=2 '
            args.append("symbol_level=1")
        return args

    def package(self):
        copy(
            self,
            "*.h",
            os.path.join(self.source_folder, "src"),
            os.path.join(self.package_folder, "include"),
        )
        copy(
            self,
            "*.inc",
            os.path.join(self.source_folder, "src"),
            os.path.join(self.package_folder, "include"),
        )

        copy(
            self,
            "*webrtc.lib",
            self.build_folder,
            os.path.join(self.package_folder, "lib"),
            keep_path=False,
        )
        copy(
            self,
            "*webrtc.dll",
            self.build_folder,
            os.path.join(self.package_folder, "bin"),
            keep_path=False,
        )
        copy(
            self,
            "*libwebrtc.so",
            self.build_folder,
            os.path.join(self.package_folder, "lib"),
            keep_path=False,
        )
        copy(
            self,
            "*libwebrtc.dylib",
            self.build_folder,
            os.path.join(self.package_folder, "lib"),
            keep_path=False,
        )
        copy(
            self,
            "*libwebrtc.a",
            self.build_folder,
            os.path.join(self.package_folder, "lib"),
            keep_path=False,
        )

    def package_info(self):
        self.cpp_info.libs = ["webrtc"]
        self.cpp_info.includedirs = [
            "include",
            "include/api",
            "include/call",
            "include/common_video",
            "include/logging",
            "include/media",
            "include/modules",
            "include/p2p",
            "include/rtc_base",
            "include/system_wrappers",
            "include/third_party/abseil-cpp",
            "include/third_party/boringssl/src/include",
            "include/third_party/libyuv/include",
        ]
        if self.settings.os == "Windows":
            self.cpp_info.defines = ["WEBRTC_WIN", "NOMINMAX"]
            self.cpp_info.system_libs = [
                "secur32",
                "winmm",
                "dmoguids",
                "wmcodecdspuuid",
                "msdmo",
                "Strmiids",
            ]
        if self.settings.os == "Linux":
            self.cpp_info.system_libs = ["dl"]
            self.cpp_info.defines = ["WEBRTC_POSIX", "WEBRTC_LINUX"]
        if self.settings.os == "Macos":
            self.cpp_info.defines = ["WEBRTC_POSIX", "WEBRTC_MAC"]
        if self.settings.os == "iOS":
            self.cpp_info.defines = ["WEBRTC_POSIX", "WEBRTC_IOS", "WEBRTC_MAC"]
        if self.options.use_h264:
            self.cpp_info.defines += ["WEBRTC_USE_H264"]
