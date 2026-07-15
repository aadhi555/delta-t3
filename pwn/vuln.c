#include <stdio.h>
#include <unistd.h>

// Hidden function: never called from main(). Prints the flag.
void win() {
    printf("CTF{st4ck_sm4sh1ng_f0r_th3_w1n}\n");
    fflush(stdout);
}

void vulnerable() {
    char buffer[64];          // fixed-size stack buffer
    printf("Enter your name: ");
    fflush(stdout);
    read(0, buffer, 200);     // BUG: reads up to 200 bytes into a 64-byte buffer
    printf("Hello, %s\n", buffer);
}

int main() {
    vulnerable();
    printf("Goodbye.\n");
    return 0;
}