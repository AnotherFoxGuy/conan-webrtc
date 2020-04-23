import os
from conans import ConanFile, CMake, tools

class WebrtcConan(ConanFile):
    name = "google-webrtc"
    version = "m79"
    license = "MIT"
    author = "Markus Lanner <contact@markus-lanner.com>"
    url = "github.com/freckled-dev/conan-google-webrtc"
    description = "Google Webrtc"
    topics = ("webrtc", "google")
    settings = "os", "compiler", "build_type", "arch"
    options = {"shared": [False]}
    default_options = {"shared": False}
    no_copy_source = True
    _webrtc_source = ""
    _depot_tools_dir = ""

    def build_requirements(self):
        if self.settings.os != "Windows":
            self.build_requires("google-gn/1.0")

    def source(self):
        self.setup_vars()
        if self.settings.os == "Windows":
            tools.download("https://storage.googleapis.com/chrome-infra/depot_tools.zip", "depot_tools.zip")
            tools.unzip("depot_tools.zip", destination="depot_tools")
            with tools.environment_append({"PATH": [self._depot_tools_dir]}):
                self.run("gclient")
                self.run("fetch --nohooks webrtc")
                with tools.chdir('src'):
                    self.run("git checkout -b m79 branch-heads/m79")
                    self.run("gclient sync -D")
        else:
            # optimised. much quickler and lighter
            git = tools.Git(folder="src")
            git.clone("https://github.com/freckled-dev/google-webrtc.git", "master")

    def build(self):
        self.setup_vars()
        # gn gen out/Default --args='is_debug=true use_custom_libcxx=false
        #   use_custom_libcxx_for_host=false cc_wrapper="ccache" use_rtti=true
        #   is_clang=true use_sysroot=false treat_warnings_as_errors=false
        #   rtc_include_tests=false libyuv_include_tests=false
        #   clang_base_path="/usr" clang_use_chrome_plugins=false
        #   use_lld=false use_gold=false'

        args = ""
        build_type = self.settings.get_safe("build_type", default="Release")
        if build_type == "Debug":
            args += "is_debug=true "
        else:
            args += "is_debug=false "
        # no tests
        args += "rtc_include_tests=false libyuv_include_tests=false "
        # no tools
        args += "rtc_build_tools=false "
        if self.settings.os == "Windows":
            args += self.create_windows_arguments()
        if self.settings.os == "Linux":
            args += self.create_linux_arguments()
        call = "gn gen \"%s\" --args=\"%s\"" % (self.build_folder, args)
        self.output.info("call:%s" % (call))
        with tools.vcvars(self.settings):
            with tools.chdir(self._webrtc_source):
                if self.settings.os == "Windows":
                    with tools.environment_append({"PATH": [self._depot_tools_dir]}):
                        self.run(call)
                else:
                    self.run(call)
            with tools.chdir(self.build_folder):
                self.run('ninja')

    def setup_vars(self):
        self._depot_tools_dir = os.path.join(self.source_folder, "depot_tools")
        self.output.info("depot_tools_dir '%s'" % (self._depot_tools_dir))
        self._webrtc_source = os.path.join(self.source_folder, "src")

    def create_windows_arguments(self):
        args = ""
        return args

    def create_linux_arguments(self):
        args = "use_rtti=true treat_warnings_as_errors=false "
        args += "use_sysroot=false "
        # no bundled libc++
        args += "use_custom_libcxx=false use_custom_libcxx_for_host=false "
        compiler = self.settings.compiler
        if compiler == "gcc":
            args += "is_clang=false use_gold=false use_lld=false "
        else:
            self.output.error("the compiler '%s' is not tested" % (compiler))
        if tools.which('ccache'):
            args += 'cc_wrapper=\\"ccache\\" '
        return args

    def package(self):
        self.copy("api/*.h", dst="include", src="src")
        self.copy("call/*.h", dst="include", src="src")
        self.copy("common_types.h", dst="include", src="src")
        self.copy("common_video/*.h", dst="include", src="src")
        self.copy("logging/*.h", dst="include", src="src")
        self.copy("media/*.h", dst="include", src="src")
        self.copy("modules/*.h", dst="include", src="src")
        self.copy("p2p/*.h", dst="include", src="src")
        self.copy("rtc_base/*.h", dst="include", src="src")
        self.copy("system_wrappers/*.h", dst="include", src="src")
        self.copy("absl/*.h", dst="include",
                src="src/third_party/abseil-cpp")

        self.copy("*webrtc.lib", dst="lib", keep_path=False)
        self.copy("*webrtc.dll", dst="bin", keep_path=False)
        self.copy("*libwebrtc.so", dst="lib", keep_path=False)
        self.copy("*libwebrtc.dylib", dst="lib", keep_path=False)
        self.copy("*libwebrtc.a", dst="lib", keep_path=False)

    def package_info(self):
        self.cpp_info.libs = ["webrtc"]
        if self.settings.os == "Windows":
            self.cpp_info.defines = ["WEBRTC_WINDOWS"]
        if self.settings.os == "Linux":
            self.cpp_info.system_libs = ["dl"]
            self.cpp_info.defines = ["WEBRTC_POSIX", "WEBRTC_LINUX"]

