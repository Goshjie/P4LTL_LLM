#include <iostream>
#include <sstream>
#include <string>

#include "frontends/parsers/p4ltl/p4ltlparser.hpp"
#include "frontends/parsers/p4ltl/p4ltllexer.hpp"
#include "frontends/parsers/p4ltl/p4ltlast.hpp"

namespace {

std::string readStdin() {
    std::ostringstream buffer;
    buffer << std::cin.rdbuf();
    return buffer.str();
}

void printUsage(const char* argv0) {
    std::cerr << "Usage: " << argv0 << " [--formula <text> | --stdin]\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    std::string formula;

    if (argc == 3 && std::string(argv[1]) == "--formula") {
        formula = argv[2];
    } else if (argc == 2 && std::string(argv[1]) == "--stdin") {
        formula = readStdin();
    } else {
        printUsage(argv[0]);
        return 2;
    }

    std::istringstream input(formula);
    P4LTL::Scanner scanner{input, std::cerr};
    P4LTL::AstNode* root = nullptr;
    P4LTL::P4LTLParser parser{scanner, root};

    const int result = parser.parse();
    if (result == 0 && root != nullptr) {
        std::cout << root->toString() << "\n";
        return 0;
    }

    std::cerr << "ERROR: error when parsing P4LTL: " << formula << "\n";
    return 1;
}
