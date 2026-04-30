import { Meteors } from "@/components/ui/meteors";
import TypingText from "@/components/ui/typing_text";
import { Button } from "@/components/ui/button"
import SmoothScroll from "@/components/ui/smooth-scroll";
import Link from "next/dist/client/link";

export default function AboutPage() {
    return (
        <SmoothScroll>
            <main className="w-full">
                <section className="sticky top-0 h-screen relative flex items-center justify-center bg-gradient-to-b from-black to-gray-900 overflow-hidden">
                    <Meteors color="#88c0d0" tailColor="rgba(136, 192, 208, 0.5)">
                        <div className="flex flex-col items-center justify-center space-y-6">
                            <TypingText
                                text={["welcome to ukiyo"]}
                                typingSpeed={55}
                                deletingSpeed={50}
                                pauseDuration={0}
                                loop={true}
                                className="text-4xl text-white"
                                cursorCharacter="|"
                                showCursor={true}
                                />

                            <TypingText
                                text={["", "the all in one ai-powered building platform"]}
                                typingSpeed={55}
                                deletingSpeed={50}
                                pauseDuration={1400}
                                loop={false}
                                className="text-4xl text-white"
                                cursorCharacter="|"
                                />
                            </div>
                        </Meteors>
                    </section>
                </main>
        </SmoothScroll>
    );
}
